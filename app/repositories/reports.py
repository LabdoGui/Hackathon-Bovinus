"""Consultas leves (colunas, não entidades) para os relatórios.

As somas são feitas em Python com ``Decimal``: o SQLite devolve ``float`` em
``SUM`` de colunas ``NUMERIC``, o que introduziria erros de arredondamento.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import TransactionStatus
from app.models import Transaction, TransactionItem

CHUNK = 2000


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _stream(self, statement: Any) -> Iterator[Any]:
        result = self.session.execute(statement.execution_options(yield_per=CHUNK))
        yield from result

    def transactions(
        self, start: datetime, end: datetime, statuses: Sequence[TransactionStatus] | None = None
    ) -> Iterator[Any]:
        statement = select(
            Transaction.id,
            Transaction.code,
            Transaction.created_at,
            Transaction.status,
            Transaction.gross_weight_g,
            Transaction.tare_g,
            Transaction.net_weight_g,
            Transaction.price_per_kg,
            Transaction.charged_amount,
            Transaction.food_cost,
            Transaction.gross_margin,
            Transaction.gross_margin_pct,
            Transaction.requires_review,
            Transaction.review_reasons,
            Transaction.reviewed_at,
            Transaction.recognition_result_id,
        ).where(Transaction.created_at >= start, Transaction.created_at < end)
        if statuses:
            statement = statement.where(Transaction.status.in_(list(statuses)))
        return self._stream(statement.order_by(Transaction.created_at, Transaction.code))

    def items(
        self, start: datetime, end: datetime, statuses: Sequence[TransactionStatus] | None = None
    ) -> Iterator[Any]:
        statement = (
            select(
                TransactionItem.transaction_id,
                TransactionItem.food_id,
                TransactionItem.food_name,
                TransactionItem.source,
                TransactionItem.weight_g,
                TransactionItem.cost,
                TransactionItem.is_corrected,
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(Transaction.created_at >= start, Transaction.created_at < end)
        )
        if statuses:
            statement = statement.where(Transaction.status.in_(list(statuses)))
        return self._stream(statement.order_by(TransactionItem.transaction_id, TransactionItem.position))
