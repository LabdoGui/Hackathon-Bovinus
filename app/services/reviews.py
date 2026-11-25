"""Revisão humana de transações: correção de alimentos, proporções e pesos.

Regras:
* só transações ``pending_review`` podem ser corrigidas/confirmadas;
* o operador envia a lista completa de itens após a correção (itens omitidos são
  removidos; itens sem ``item_id`` são acrescentados);
* os valores ORIGINAIS (alimento, proporção, peso) ficam no próprio item na
  primeira correção e nunca são sobrescritos por correções seguintes;
* todo o estado antes/depois, com o motivo e o operador, vai para a auditoria;
* custo, margem e motivos de revisão são recalculados com o motor de cálculo.
"""

from __future__ import annotations

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
from app.schemas.transaction import TransactionReviewIn
from app.services.audit import AuditService
from app.services.calculations import (
    PlateCalculation,
    PlateItemInput,
    calculate_plate,
    calculate_plate_from_weights,
)
from app.services.costing import food_cost_per_kg
from app.services.transactions import TransactionService
from app.utils.serialization import json_safe

PROPORTION_SUM_TOLERANCE = Decimal("0.01")
COMPUTED_REASONS = {
    ReviewReason.COST_UNAVAILABLE.value,
    ReviewReason.INACTIVE_FOOD.value,
    ReviewReason.UNKNOWN_FOOD.value,
}


class TransactionReviewService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.transactions = TransactionRepository(session)
        self.foods = FoodRepository(session)
        self.audit = AuditService(session)

    # ----------------------------------------------------------------- público
    def review(self, transaction_id: uuid.UUID, data: TransactionReviewIn, operator: Operator) -> Transaction:
        tx = self.transactions.get(transaction_id)
        if tx is None:
            raise NotFoundError("Transação não encontrada.")
        if tx.status is not TransactionStatus.PENDING_REVIEW:
            raise ConflictError(
                f"Somente transações em revisão podem ser corrigidas ou confirmadas (status atual: {tx.status.value}).",
                code="transaction_not_reviewable",
            )

        before = TransactionService.snapshot(tx)
        changes: list[dict[str, Any]] = []
        if data.items is not None:
            changes = self._apply_items(tx, data)
        if data.notes is not None and data.notes != tx.notes:
            changes.append({"type": "notes", "from": tx.notes, "to": data.notes})
            tx.notes = data.notes
        if not changes and not data.confirm:
            raise BusinessRuleError("Nenhuma alteração em relação ao estado atual da transação.")

        if changes:
            self.session.flush()
            after = TransactionService.snapshot(tx)
            after["changes"] = json_safe(changes)
            self.audit.record(
                entity_type="transaction",
                entity_id=tx.id,
                action=AuditAction.CORRECTION,
                operator_id=operator.id,
                before=before,
                after=after,
                reason=data.reason,
            )
        if data.confirm:
            self._confirm(tx, data.reason, operator)

        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Não foi possível gravar a revisão (conflito de integridade).") from exc
        self.session.expire(tx)
        return self.transactions.get(tx.id)  # type: ignore[return-value]

    # --------------------------------------------------------------- confirmação
    def _confirm(self, tx: Transaction, reason: str, operator: Operator) -> None:
        if not tx.items or any(item.food_id is None for item in tx.items):
            raise BusinessRuleError(
                "Há itens sem alimento cadastrado. Associe cada item a um alimento (items) antes de confirmar.",
                code="items_without_food",
            )
        now = datetime.now(UTC)
        before = {"status": tx.status.value, "requires_review": tx.requires_review, "review_reasons": list(tx.review_reasons)}
        tx.status = TransactionStatus.CONFIRMED
        tx.requires_review = False
        tx.confirmed_at = now
        tx.reviewed_at = now
        tx.reviewed_by_id = operator.id
        self.audit.record(
            entity_type="transaction",
            entity_id=tx.id,
            action=AuditAction.STATUS_CHANGE,
            operator_id=operator.id,
            before=before,
            after={"status": tx.status.value, "requires_review": False, "review_reasons": list(tx.review_reasons)},
            reason=reason,
        )

    # ---------------------------------------------------------------- correções
    def _apply_items(self, tx: Transaction, data: TransactionReviewIn) -> list[dict[str, Any]]:
        assert data.items is not None
        existing = {item.id: item for item in tx.items}
        unknown = [str(i.item_id) for i in data.items if i.item_id is not None and i.item_id not in existing]
        if unknown:
            raise BusinessRuleError("Itens que não pertencem a esta transação.", details={"item_ids": unknown})

        foods = self.foods.get_many(i.food_id for i in data.items)
        missing = [str(i.food_id) for i in data.items if i.food_id not in foods]
        if missing:
            raise BusinessRuleError("Alimentos não encontrados.", details={"food_ids": missing})
        ordered_foods = [foods[i.food_id] for i in data.items]
        calculation = self._calculate(tx, data, ordered_foods)

        changes: list[dict[str, Any]] = []
        new_items: list[TransactionItem] = []
        kept_ids: set[uuid.UUID] = set()
        for index, (inp, food, result) in enumerate(zip(data.items, ordered_foods, calculation.items, strict=True)):
            if inp.item_id is None:
                new_items.append(self._new_item(index, food, result))
                changes.append({"type": "added", "food": food.name, "proportion": result.proportion, "weight_g": result.weight_g})
                continue
            item = existing[inp.item_id]
            kept_ids.add(item.id)
            change = self._update_item(item, index, food, result)
            if change:
                changes.append(change)
            new_items.append(item)

        for item_id, item in existing.items():
            if item_id not in kept_ids:
                changes.append(
                    {"type": "removed", "item_id": item.id, "food": item.food_name, "proportion": item.proportion, "weight_g": item.weight_g}
                )

        tx.items = new_items
        self._update_totals(tx, calculation, ordered_foods)
        return changes

    def _calculate(self, tx: Transaction, data: TransactionReviewIn, foods: list[Food]) -> PlateCalculation:
        assert data.items is not None
        costs = [food_cost_per_kg(food) for food in foods]
        if data.items[0].weight_g is not None:
            weights = [i.weight_g for i in data.items]
            total = sum(weights, Decimal(0))
            tolerance = max(
                self.settings.review_weight_tolerance_g, tx.net_weight_g * self.settings.review_weight_tolerance_pct / 100
            )
            if abs(total - tx.net_weight_g) > tolerance:
                raise BusinessRuleError(
                    f"A soma dos pesos informados ({total} g) difere do peso líquido ({tx.net_weight_g} g) "
                    f"além da tolerância de {tolerance} g.",
                    code="weights_do_not_match_net",
                    details={"sum_weight_g": str(total), "net_weight_g": str(tx.net_weight_g), "tolerance_g": str(tolerance)},
                )
            return calculate_plate_from_weights(
                gross_weight_g=tx.gross_weight_g,
                tare_g=tx.tare_g,
                price_per_kg=tx.price_per_kg,
                weights_g=weights,
                costs_per_kg=costs,
            )
        proportions = [i.proportion for i in data.items]
        total = sum(proportions, Decimal(0))
        if abs(total - 1) > PROPORTION_SUM_TOLERANCE:
            raise BusinessRuleError(
                f"A soma das proporções deve ser 1 (±{PROPORTION_SUM_TOLERANCE}); recebido {total}.",
                code="proportions_do_not_sum_one",
            )
        return calculate_plate(
            gross_weight_g=tx.gross_weight_g,
            tare_g=tx.tare_g,
            price_per_kg=tx.price_per_kg,
            items=[PlateItemInput(p, c) for p, c in zip(proportions, costs, strict=True)],
        )

    @staticmethod
    def _extra_for(cost_per_kg: Decimal | None, extra: dict[str, Any] | None) -> dict[str, Any] | None:
        merged = {k: v for k, v in (extra or {}).items() if k not in {"cost_unavailable", "food_not_in_catalog"}}
        if cost_per_kg is None:
            merged["cost_unavailable"] = "sem_ficha_tecnica"
        return merged or None

    def _update_item(self, item: TransactionItem, position: int, food: Food, result: Any) -> dict[str, Any] | None:
        diff: dict[str, Any] = {}
        if food.id != item.food_id:
            diff["food"] = {"from": item.food_name, "to": food.name}
        if result.proportion != item.proportion:
            diff["proportion"] = {"from": item.proportion, "to": result.proportion}
        if result.weight_g != item.weight_g:
            diff["weight_g"] = {"from": item.weight_g, "to": result.weight_g}
        if diff and not item.is_corrected:
            # Primeira correção: guarda os valores originais (nunca sobrescritos depois).
            item.original_food_id = item.food_id
            item.original_food_name = item.food_name
            item.original_proportion = item.proportion
            item.original_weight_g = item.weight_g
        if diff:
            item.is_corrected = True
        item.position = position
        item.food_id = food.id
        item.food_name = food.name
        item.proportion = result.proportion
        item.weight_g = result.weight_g
        item.cost_per_kg = result.cost_per_kg
        item.cost = result.cost
        item.extra = self._extra_for(result.cost_per_kg, item.extra)
        return {"type": "corrected", "item_id": item.id, "food": food.name, "fields": diff} if diff else None

    def _new_item(self, position: int, food: Food, result: Any) -> TransactionItem:
        extra = self._extra_for(result.cost_per_kg, {"added_in_review": True})
        return TransactionItem(
            position=position,
            food_id=food.id,
            food_name=food.name,
            recognition_class=food.recognition_class,
            source=ItemSource.MANUAL,
            confidence=None,
            proportion=result.proportion,
            weight_g=result.weight_g,
            cost_per_kg=result.cost_per_kg,
            cost=result.cost,
            is_corrected=True,
            extra=extra,
        )

    @staticmethod
    def _update_totals(tx: Transaction, calculation: PlateCalculation, foods: list[Food]) -> None:
        tx.food_cost = calculation.food_cost
        tx.gross_margin = calculation.gross_margin
        tx.gross_margin_pct = calculation.gross_margin_pct
        reasons = [r for r in tx.review_reasons if r not in COMPUTED_REASONS]
        if not calculation.cost_complete:
            reasons.append(ReviewReason.COST_UNAVAILABLE.value)
        if any(not food.active for food in foods):
            reasons.append(ReviewReason.INACTIVE_FOOD.value)
        tx.review_reasons = reasons
