from __future__ import annotations

from sqlalchemy import select

from app.models import ScaleReading
from app.repositories.base import Repository


class ScaleReadingRepository(Repository[ScaleReading]):
    model = ScaleReading

    def list(self, *, limit: int, offset: int) -> tuple[list[ScaleReading], int]:
        return self.paginate(select(ScaleReading), limit=limit, offset=offset, order_by=[ScaleReading.created_at.desc()])
