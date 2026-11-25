import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RecognitionMode, RecognitionStatus
from app.models.base import Base, CreatedAtMixin, JSONType, UUIDPrimaryKeyMixin, str_enum
from app.models.image_capture import ImageCapture


class RecognitionResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Resultado de uma execução do serviço de reconhecimento sobre uma imagem.

    ``detections`` guarda a lista de alimentos identificados (nome, classe,
    confiança, área segmentada, proporção, peso estimado e origem).
    ``is_simulated`` é verdadeiro quando o resultado vem do modo mock — nesse
    caso não existe modelo treinado envolvido.
    """

    __tablename__ = "recognition_results"
    __table_args__ = (
        CheckConstraint(
            "overall_confidence IS NULL OR (overall_confidence >= 0 AND overall_confidence <= 1)",
            name="confidence_range",
        ),
    )

    image_capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("image_captures.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[RecognitionMode] = mapped_column(str_enum(RecognitionMode, 16), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(60))
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[RecognitionStatus] = mapped_column(str_enum(RecognitionStatus, 16), nullable=False, index=True)
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detections: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(String(255))
    processing_ms: Mapped[int | None] = mapped_column(Integer)

    image_capture: Mapped[ImageCapture] = relationship()
