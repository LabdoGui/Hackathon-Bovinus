import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CaptureSource
from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum


class ImageCapture(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Imagem capturada pela webcam ou enviada manualmente, com métricas de qualidade."""

    __tablename__ = "image_captures"
    __table_args__ = (
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
    )

    source: Mapped[CaptureSource] = mapped_column(str_enum(CaptureSource, 16), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    brightness: Mapped[float | None] = mapped_column(Float)
    sharpness: Mapped[float | None] = mapped_column(Float)
    is_dark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_blurry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device_index: Mapped[int | None] = mapped_column(Integer)
    # Cópia amigável feita para o usuário (ex.: "Prato 0001" e o caminho do arquivo); vazia se desligada ou falhou.
    label: Mapped[str | None] = mapped_column(String(60))
    export_path: Mapped[str | None] = mapped_column(String(500))
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operators.id", ondelete="SET NULL"), index=True)
