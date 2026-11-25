import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ItemSource, TransactionStatus
from app.models.base import Base, JSONType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, str_enum

if TYPE_CHECKING:
    from app.models.food import Food
    from app.models.image_capture import ImageCapture
    from app.models.operator import Operator
    from app.models.recognition import RecognitionResult
    from app.models.scale_reading import ScaleReading


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pesagem/venda de um prato.

    Valores monetários e de peso são fotografados no momento do cálculo, de modo
    que mudanças futuras em fichas técnicas não alteram transações passadas.
    ``gross_margin`` é a margem bruta alimentar estimada (valor cobrado - custo
    alimentar estimado); não representa lucro líquido.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("gross_weight_g >= 0", name="gross_weight_non_negative"),
        CheckConstraint("tare_g >= 0", name="tare_non_negative"),
        CheckConstraint("net_weight_g >= 0", name="net_weight_non_negative"),
        CheckConstraint("price_per_kg >= 0", name="price_non_negative"),
        CheckConstraint("charged_amount >= 0", name="charged_non_negative"),
        CheckConstraint("food_cost IS NULL OR food_cost >= 0", name="food_cost_non_negative"),
        Index("ix_transactions_status_created_at", "status", "created_at"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Hash do conteúdo da requisição original, para detectar reuso da chave com outro conteúdo.
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[TransactionStatus] = mapped_column(
        str_enum(TransactionStatus, 20), nullable=False, default=TransactionStatus.DRAFT
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operators.id", ondelete="SET NULL"), index=True)
    # Única: uma leitura da balança só pode originar uma transação.
    scale_reading_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scale_readings.id", ondelete="SET NULL"), index=True, unique=True
    )
    image_capture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("image_captures.id", ondelete="SET NULL"), index=True
    )
    # Único: um resultado de reconhecimento só pode originar uma transação.
    recognition_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recognition_results.id", ondelete="SET NULL"), index=True, unique=True
    )

    gross_weight_g: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    tare_g: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False, default=Decimal("0"))
    net_weight_g: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    price_per_kg: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    charged_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    food_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gross_margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gross_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))

    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    review_reasons: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    items: Mapped[list["TransactionItem"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionItem.position",
    )
    operator: Mapped["Operator | None"] = relationship()
    scale_reading: Mapped["ScaleReading | None"] = relationship()
    image_capture: Mapped["ImageCapture | None"] = relationship()
    recognition_result: Mapped["RecognitionResult | None"] = relationship()


class TransactionItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alimento de uma transação, com peso distribuído e custo estimado.

    Quando o operador corrige o item, os valores originais ficam em
    ``original_*`` e ``is_corrected`` passa a ser verdadeiro.
    """

    __tablename__ = "transaction_items"
    __table_args__ = (
        CheckConstraint("proportion >= 0 AND proportion <= 1", name="proportion_range"),
        CheckConstraint("weight_g >= 0", name="weight_non_negative"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="cost_non_negative"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    food_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"), index=True)
    food_name: Mapped[str] = mapped_column(String(120), nullable=False)
    recognition_class: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[ItemSource] = mapped_column(str_enum(ItemSource, 16), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    proportion: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    weight_g: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    cost_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    is_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    original_food_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"))
    original_food_name: Mapped[str | None] = mapped_column(String(120))
    original_proportion: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    original_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    transaction: Mapped[Transaction] = relationship(back_populates="items")
    food: Mapped["Food | None"] = relationship(foreign_keys=[food_id])
