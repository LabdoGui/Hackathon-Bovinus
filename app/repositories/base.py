"""Camada de persistência: consultas SQLAlchemy isoladas das regras de negócio."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.models import Base


class Repository[ModelT: Base]:
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()

    def exists(self, *conditions: ColumnElement[bool]) -> bool:
        return self.session.scalar(select(select(self.model).where(*conditions).exists())) or False

    def paginate(
        self,
        statement: Select[Any],
        *,
        limit: int,
        offset: int,
        order_by: Sequence[Any] = (),
    ) -> tuple[list[ModelT], int]:
        total = self.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
        rows = self.session.scalars(statement.order_by(*order_by).limit(limit).offset(offset)).unique().all()
        return list(rows), total
