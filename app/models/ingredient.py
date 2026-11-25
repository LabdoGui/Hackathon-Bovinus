from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import IngredientUnit
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum

if TYPE_CHECKING:
    from app.models.recipe import RecipeIngredient


class Ingredient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Insumo comprado, com custo por unidade de compra (R$/kg, R$/l ou R$/un)."""

    __tablename__ = "ingredients"
    __table_args__ = (CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    unit: Mapped[IngredientUnit] = mapped_column(str_enum(IngredientUnit, 8), nullable=False, default=IngredientUnit.KG)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    recipe_items: Mapped[list["RecipeIngredient"]] = relationship(back_populates="ingredient")
