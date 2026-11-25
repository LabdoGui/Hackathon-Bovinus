"""Criação e consulta de transações (pesagem + cálculo de custo e margem)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import AuditAction, ItemSource, RecognitionStatus, ReviewReason, TransactionStatus
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import Food, Operator, RecognitionResult, Transaction, TransactionItem
from app.repositories.catalog import FoodRepository
from app.repositories.transaction import TransactionRepository
from app.schemas.transaction import (
    CalculationPreviewIn,
    TransactionCreate,
    TransactionFromRecognition,
    TransactionItemIn,
)
from app.services.audit import AuditService
from app.services.calculations import PlateCalculation, PlateItemInput, calculate_plate
from app.services.costing import food_cost_per_kg
from app.services.scale_readings import ScaleReadingService
from app.utils.ids import transaction_code
from app.utils.serialization import entity_snapshot


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ItemSpec:
    """Item a gravar: alimento cadastrado (ou ``None`` se não reconhecido no cadastro) e sua proporção."""

    food: Food | None
    name: str
    recognition_class: str | None
    proportion: Decimal
    source: ItemSource
    confidence: Decimal | None = None
    extra: dict[str, Any] | None = None


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
        self, *, gross: Decimal, tare: Decimal, price: Decimal, proportions: list[Decimal], foods: list[Food | None]
    ) -> tuple[PlateCalculation, list[str]]:
        costs = [food_cost_per_kg(food) if food is not None else None for food in foods]
        calculation = calculate_plate(
            gross_weight_g=gross,
            tare_g=tare,
            price_per_kg=price,
            items=[PlateItemInput(p, cost) for p, cost in zip(proportions, costs, strict=True)],
        )
        reasons: list[str] = []
        if not calculation.cost_complete:
            reasons.append(ReviewReason.COST_UNAVAILABLE.value)
        if any(food is not None and not food.active for food in foods):
            reasons.append(ReviewReason.INACTIVE_FOOD.value)
        return calculation, reasons

    def preview(self, data: CalculationPreviewIn) -> dict[str, Any]:
        """Calcula sem gravar nada (útil para conferência e testes do motor de cálculo)."""
        foods = self._load_foods(data.items)
        calculation, reasons = self._calculate(
            gross=data.gross_weight_g,
            tare=data.tare_g,
            price=self._price(data.price_per_kg),
            proportions=[item.proportion for item in data.items],
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
        """Cria a transação com alimentos informados manualmente.

        Retorna ``(transação, criada)``; ``criada=False`` em repetição idempotente.
        """
        fingerprint = _fingerprint({"kind": "manual", **data.model_dump(mode="json")})
        if idempotency_key and (existing := self.repository.get_by_idempotency_key(idempotency_key)):
            return self._replay(existing, fingerprint), False
        foods = self._load_foods(data.items)
        specs = [
            ItemSpec(food, food.name, food.recognition_class, item.proportion, ItemSource.MANUAL)
            for food, item in zip(foods, data.items, strict=True)
        ]
        return self._store(
            reading_id=data.scale_reading_id,
            specs=specs,
            price_per_kg=data.price_per_kg,
            notes=data.notes,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            operator=operator,
            recognition=None,
        )

    def create_from_recognition(
        self, data: TransactionFromRecognition, *, idempotency_key: str | None, operator: Operator | None
    ) -> tuple[Transaction, bool]:
        """Cria a transação a partir de um resultado de reconhecimento e uma leitura da balança.

        Os alimentos reconhecidos entram como itens ``source=recognition``. Resultado incerto,
        alimento fora do cadastro, custo desconhecido ou reconhecimento simulado levam a
        transação para revisão humana (``pending_review``).
        """
        fingerprint = _fingerprint({"kind": "recognition", **data.model_dump(mode="json")})
        if idempotency_key and (existing := self.repository.get_by_idempotency_key(idempotency_key)):
            return self._replay(existing, fingerprint), False

        recognition = self.session.get(RecognitionResult, data.recognition_result_id)
        if recognition is None:
            raise BusinessRuleError(
                "Resultado de reconhecimento não encontrado.",
                details={"recognition_result_id": str(data.recognition_result_id)},
            )
        if recognition.status is RecognitionStatus.FAILED:
            raise BusinessRuleError(
                "O reconhecimento falhou; informe os alimentos manualmente (POST /api/v1/transactions)."
            )
        detections = [d for d in recognition.detections if Decimal(str(d["proportion"])) > 0]
        if not detections:
            raise BusinessRuleError(
                "Nenhum alimento foi reconhecido; informe os alimentos manualmente (POST /api/v1/transactions)."
            )
        if self.repository.is_recognition_used(recognition.id):
            raise ConflictError("Este resultado de reconhecimento já foi usado em outra transação.")

        foods = self.foods.get_many(
            uuid.UUID(str(d["food_id"])) for d in detections if d.get("food_id")
        )
        specs = []
        for detection in detections:
            food = foods.get(uuid.UUID(str(detection["food_id"]))) if detection.get("food_id") else None
            extra = {
                "recognition_estimated_weight_g": detection.get("estimated_weight_g"),
                "recognition_segmented_area_ratio": detection.get("segmented_area_ratio"),
                "recognition_origin": detection.get("source"),
            }
            if food is None:
                extra["food_not_in_catalog"] = True
            specs.append(
                ItemSpec(
                    food=food,
                    name=food.name if food else str(detection["name"]),
                    recognition_class=str(detection["recognition_class"]),
                    proportion=Decimal(str(detection["proportion"])),
                    source=ItemSource.RECOGNITION,
                    confidence=Decimal(str(detection["confidence"])),
                    extra=extra,
                )
            )
        reasons = list(recognition.review_reasons or [])
        if recognition.is_simulated and self.settings.recognition_mock_requires_review:
            reasons.append(ReviewReason.SIMULATED_RECOGNITION.value)
        return self._store(
            reading_id=data.scale_reading_id,
            specs=specs,
            price_per_kg=data.price_per_kg,
            notes=data.notes,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            operator=operator,
            recognition=recognition,
            extra_reasons=reasons,
        )

    def _store(
        self,
        *,
        reading_id: uuid.UUID,
        specs: list[ItemSpec],
        price_per_kg: Decimal | None,
        notes: str | None,
        idempotency_key: str | None,
        fingerprint: str,
        operator: Operator | None,
        recognition: RecognitionResult | None,
        extra_reasons: list[str] | None = None,
    ) -> tuple[Transaction, bool]:
        reading = self.readings.repository.get(reading_id)
        if reading is None:
            raise BusinessRuleError("Leitura da balança não encontrada.", details={"scale_reading_id": str(reading_id)})
        issues = self.readings.issues(reading, check_age=True)
        if issues:
            raise BusinessRuleError("Leitura da balança não pode ser usada.", details={"issues": issues})
        if self.repository.is_reading_used(reading.id):
            raise ConflictError("Esta leitura da balança já foi usada em outra transação.")

        calculation, reasons = self._calculate(
            gross=reading.gross_weight_g,
            tare=reading.tare_g,
            price=self._price(price_per_kg),
            proportions=[spec.proportion for spec in specs],
            foods=[spec.food for spec in specs],
        )
        for reason in extra_reasons or []:
            if reason not in reasons:
                reasons.append(reason)

        now = datetime.now(UTC)
        requires_review = bool(reasons)
        transaction = Transaction(
            code=transaction_code(now),
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else None,
            status=TransactionStatus.PENDING_REVIEW if requires_review else TransactionStatus.CONFIRMED,
            operator_id=operator.id if operator else None,
            scale_reading_id=reading.id,
            image_capture_id=recognition.image_capture_id if recognition else None,
            recognition_result_id=recognition.id if recognition else None,
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
            notes=notes,
            confirmed_at=None if requires_review else now,
        )
        transaction.items = []
        for index, (spec, result) in enumerate(zip(specs, calculation.items, strict=True)):
            extra = dict(spec.extra or {})
            if result.cost_per_kg is None:
                extra["cost_unavailable"] = "sem_ficha_tecnica" if spec.food is not None else "alimento_fora_do_cadastro"
            transaction.items.append(
                TransactionItem(
                    position=index,
                    food_id=spec.food.id if spec.food else None,
                    food_name=spec.name,
                    recognition_class=spec.recognition_class,
                    source=spec.source,
                    confidence=spec.confidence,
                    proportion=result.proportion,
                    weight_g=result.weight_g,
                    cost_per_kg=result.cost_per_kg,
                    cost=result.cost,
                    extra=extra or None,
                )
            )
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
            raise ConflictError("Transação duplicada (leitura ou reconhecimento já utilizado).") from exc
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
