import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ScaleMode
from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum


class ScaleReading(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Leitura registrada da balança (ou falha de leitura, com ``error`` preenchido)."""

    __tablename__ = "scale_readings"
    __table_args__ = (
        CheckConstraint("gross_weight_g IS NULL OR gross_weight_g >= 0", name="gross_weight_non_negative"),
        CheckConstraint("tare_g >= 0", name="tare_non_negative"),
    )

    mode: Mapped[ScaleMode] = mapped_column(str_enum(ScaleMode, 16), nullable=False)
    gross_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    tare_g: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False, default=Decimal("0"))
    net_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    stable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device: Mapped[str | None] = mapped_column(String(64))
    raw_data: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String(255))
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operators.id", ondelete="SET NULL"), index=True)
