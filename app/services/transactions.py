"""Criação e consulta de transações (pesagem + cálculo de custo e margem)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import AuditAction, ItemSource, ReviewReason, TransactionStatus
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import Food, Operator, Transaction, TransactionItem
from app.repositories.catalog import FoodRepository
from app.repositories.transaction import TransactionRepository
from app.schemas.transaction import CalculationPreviewIn, TransactionCreate, TransactionItemIn
from app.services.audit import AuditService
from app.services.calculations import PlateCalculation, PlateItemInput, calculate_plate
from app.services.costing import food_cost_per_kg
from app.services.scale_readings import ScaleReadingService
from app.utils.ids import transaction_code
from app.utils.serialization import entity_snapshot


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TransactionService:
    def __init__(self, session: Session, settings: Settings, readings: ScaleReadingService) -> None:
        self.session = session
        self.settings = settings
        self.readings = readings
        self.repository = TransactionRepository(session)
        self.foods = FoodRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------- consultas
    def get(self, transaction_id: uuid.UUID) -> Transaction:
        transaction = self.repository.get(transaction_id)
        if transaction is None:
            raise NotFoundError("Transação não encontrada.")
        return transaction

    def list(self, **filters: Any) -> tuple[list[Transaction], int]:
        return self.repository.list(**filters)

    # --------------------------------------------------------------- cálculo
    def _price(self, price_per_kg: Decimal | None) -> Decimal:
        price = price_per_kg if price_per_kg is not None else self.settings.default_price_per_kg
        if price is None:
            raise BusinessRuleError("Informe price_per_kg ou configure DEFAULT_PRICE_PER_KG.")
        return price

    def _load_foods(self, items: list[TransactionItemIn]) -> list[Food]:
        found = self.foods.get_many(item.food_id for item in items)
        missing = [str(item.food_id) for item in items if item.food_id not in found]
        if missing:
            raise BusinessRuleError("Alimentos não encontrados.", details={"food_ids": missing})
        return [found[item.food_id] for item in items]

    def _calculate(
        self, *, gross: Decimal, tare: Decimal, price: Decimal, items: list[TransactionItemIn], foods: list[Food]
    ) -> tuple[PlateCalculation, list[str]]:
        costs = [food_cost_per_kg(food) for food in foods]
        calculation = calculate_plate(
            gross_weight_g=gross,
            tare_g=tare,
            price_per_kg=price,
            items=[PlateItemInput(item.proportion, cost) for item, cost in zip(items, costs, strict=True)],
        )
        reasons: list[str] = []
        if not calculation.cost_complete:
            reasons.append(ReviewReason.COST_UNAVAILABLE.value)
        if any(not food.active for food in foods):
            reasons.append(ReviewReason.INACTIVE_FOOD.value)
        return calculation, reasons

    def preview(self, data: CalculationPreviewIn) -> dict[str, Any]:
        """Calcula sem gravar nada (útil para conferência e testes do motor de cálculo)."""
        foods = self._load_foods(data.items)
        calculation, reasons = self._calculate(
            gross=data.gross_weight_g,
            tare=data.tare_g,
            price=self._price(data.price_per_kg),
            items=data.items,
            foods=foods,
        )
        return {
            "gross_weight_g": calculation.gross_weight_g,
            "tare_g": calculation.tare_g,
            "net_weight_g": calculation.net_weight_g,
            "price_per_kg": calculation.price_per_kg,
            "charged_amount": calculation.charged_amount,
            "food_cost": calculation.food_cost,
            "known_food_cost": calculation.known_food_cost,
            "cost_complete": calculation.cost_complete,
            "gross_margin": calculation.gross_margin,
            "gross_margin_pct": calculation.gross_margin_pct,
            "requires_review": bool(reasons),
            "review_reasons": reasons,
            "items": [
                {
                    "food_id": food.id,
                    "food_name": food.name,
                    "proportion": result.proportion,
                    "weight_g": result.weight_g,
                    "cost_per_kg": result.cost_per_kg,
                    "cost": result.cost,
                }
                for food, result in zip(foods, calculation.items, strict=True)
            ],
        }

    # ---------------------------------------------------------------- criação
    def create(
        self, data: TransactionCreate, *, idempotency_key: str | None, operator: Operator | None
    ) -> tuple[Transaction, bool]:
        """Cria a transação. Retorna ``(transação, criada)``; ``criada=False`` em repetição idempotente."""
        fingerprint = _fingerprint(data.model_dump(mode="json"))
        if idempotency_key:
            existing = self.repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return self._replay(existing, fingerprint), False

        reading = self.readings.repository.get(data.scale_reading_id)
        if reading is None:
            raise BusinessRuleError(
                "Leitura da balança não encontrada.", details={"scale_reading_id": str(data.scale_reading_id)}
            )
        issues = self.readings.issues(reading, check_age=True)
        if issues:
            raise BusinessRuleError("Leitura da balança não pode ser usada.", details={"issues": issues})
        if self.repository.is_reading_used(reading.id):
            raise ConflictError("Esta leitura da balança já foi usada em outra transação.")

        foods = self._load_foods(data.items)
        calculation, reasons = self._calculate(
            gross=reading.gross_weight_g,
            tare=reading.tare_g,
            price=self._price(data.price_per_kg),
            items=data.items,
            foods=foods,
        )
        now = datetime.now(UTC)
        requires_review = bool(reasons)
        transaction = Transaction(
            code=transaction_code(now),
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else None,
            status=TransactionStatus.PENDING_REVIEW if requires_review else TransactionStatus.CONFIRMED,
            operator_id=operator.id if operator else None,
            scale_reading_id=reading.id,
            gross_weight_g=calculation.gross_weight_g,
            tare_g=calculation.tare_g,
            net_weight_g=calculation.net_weight_g,
            price_per_kg=calculation.price_per_kg,
            charged_amount=calculation.charged_amount,
            food_cost=calculation.food_cost,
            gross_margin=calculation.gross_margin,
            gross_margin_pct=calculation.gross_margin_pct,
            requires_review=requires_review,
            review_reasons=reasons,
            notes=data.notes,
            confirmed_at=None if requires_review else now,
        )
        transaction.items = [
            TransactionItem(
                position=index,
                food_id=food.id,
                food_name=food.name,
                recognition_class=food.recognition_class,
                source=ItemSource.MANUAL,
                proportion=result.proportion,
                weight_g=result.weight_g,
                cost_per_kg=result.cost_per_kg,
                cost=result.cost,
                extra={"cost_unavailable": "sem_ficha_tecnica"} if result.cost_per_kg is None else None,
            )
            for index, (food, result) in enumerate(zip(foods, calculation.items, strict=True))
        ]
        self.session.add(transaction)
        try:
            self.session.flush()
            self.audit.record(
                entity_type="transaction",
                entity_id=transaction.id,
                action=AuditAction.CREATE,
                operator_id=transaction.operator_id,
                after=self.snapshot(transaction),
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if idempotency_key and (existing := self.repository.get_by_idempotency_key(idempotency_key)):
                return self._replay(existing, fingerprint), False
            raise ConflictError("Transação duplicada (leitura da balança já utilizada).") from exc
        return self.get(transaction.id), True

    @staticmethod
    def _replay(existing: Transaction, fingerprint: str) -> Transaction:
        if existing.idempotency_fingerprint != fingerprint:
            raise ConflictError("Idempotency-Key já utilizada com outro conteúdo.")
        return existing

    @staticmethod
    def snapshot(transaction: Transaction) -> dict[str, Any]:
        data = entity_snapshot(transaction, exclude=("idempotency_fingerprint",))
        data["items"] = [
            entity_snapshot(item, exclude=("transaction_id", "created_at", "updated_at")) for item in transaction.items
        ]
        return data

    # ----------------------------------------------------------- cancelamento
    def cancel(self, transaction_id: uuid.UUID, reason: str, operator: Operator) -> Transaction:
        transaction = self.get(transaction_id)
        if transaction.status is TransactionStatus.CANCELLED:
            raise ConflictError("Transação já está cancelada.")
        before = {"status": transaction.status.value}
        transaction.status = TransactionStatus.CANCELLED
        transaction.cancelled_at = datetime.now(UTC)
        self.audit.record(
            entity_type="transaction",
            entity_id=transaction.id,
            action=AuditAction.STATUS_CHANGE,
            operator_id=operator.id,
            before=before,
            after={"status": transaction.status.value},
            reason=reason,
        )
        self.session.commit()
        return self.get(transaction.id)
