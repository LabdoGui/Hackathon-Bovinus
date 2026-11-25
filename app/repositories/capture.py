from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import ImageCapture
from app.repositories.base import Repository


class ImageCaptureRepository(Repository[ImageCapture]):
    model = ImageCapture

    def list(self, *, limit: int, offset: int) -> tuple[list[ImageCapture], int]:
        return self.paginate(select(ImageCapture), limit=limit, offset=offset, order_by=[ImageCapture.created_at.desc()])

    def first_with_hash(self, sha256: str, *, exclude: uuid.UUID) -> ImageCapture | None:
        statement = (
            select(ImageCapture)
            .where(ImageCapture.sha256 == sha256, ImageCapture.id != exclude)
            .order_by(ImageCapture.created_at)
            .limit(1)
        )
        return self.session.scalar(statement)
