from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.enums import TransactionStatus
from app.models import Transaction
from app.repositories.base import Repository


class TransactionRepository(Repository[Transaction]):
    model = Transaction

    def _with_items(self):
        return select(Transaction).options(selectinload(Transaction.items))

    def get(self, entity_id: uuid.UUID) -> Transaction | None:
        return self.session.scalar(self._with_items().where(Transaction.id == entity_id))

    def get_by_idempotency_key(self, key: str) -> Transaction | None:
        return self.session.scalar(self._with_items().where(Transaction.idempotency_key == key))

    def get_by_code(self, code: str) -> Transaction | None:
        return self.session.scalar(select(Transaction).where(Transaction.code == code))

    def is_reading_used(self, scale_reading_id: uuid.UUID) -> bool:
        return self.exists(Transaction.scale_reading_id == scale_reading_id)

    def list(
        self,
        *,
        status: TransactionStatus | None,
        requires_review: bool | None,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Transaction], int]:
        statement = self._with_items()
        if status is not None:
            statement = statement.where(Transaction.status == status)
        if requires_review is not None:
            statement = statement.where(Transaction.requires_review.is_(requires_review))
        if created_from is not None:
            statement = statement.where(Transaction.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(Transaction.created_at < created_to)
        return self.paginate(statement, limit=limit, offset=offset, order_by=[Transaction.created_at.desc()])
