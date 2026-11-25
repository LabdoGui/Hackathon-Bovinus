from __future__ import annotations

from sqlalchemy import select

from app.models import Operator
from app.repositories.base import Repository


class OperatorRepository(Repository[Operator]):
    model = Operator

    def get_by_username(self, username: str) -> Operator | None:
        return self.session.scalar(select(Operator).where(Operator.username == username))

    def get_by_api_key_hash(self, api_key_hash: str) -> Operator | None:
        return self.session.scalar(select(Operator).where(Operator.api_key_hash == api_key_hash))

    def list(self, *, limit: int, offset: int) -> tuple[list[Operator], int]:
        return self.paginate(select(Operator), limit=limit, offset=offset, order_by=[Operator.username])
