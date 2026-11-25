from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import RecognitionResult
from app.repositories.base import Repository


class RecognitionResultRepository(Repository[RecognitionResult]):
    model = RecognitionResult

    def list(self, *, capture_id: uuid.UUID | None, limit: int, offset: int) -> tuple[list[RecognitionResult], int]:
        statement = select(RecognitionResult)
        if capture_id is not None:
            statement = statement.where(RecognitionResult.image_capture_id == capture_id)
        return self.paginate(statement, limit=limit, offset=offset, order_by=[RecognitionResult.created_at.desc()])
