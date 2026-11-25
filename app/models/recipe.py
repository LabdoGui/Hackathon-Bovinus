import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import IngredientUnit
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.food import Food
    from app.models.ingredient import Ingredient


class Recipe(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ficha técnica de uma preparação.

    ``yield_weight_g`` é o rendimento total da preparação pronta, em gramas.
    O custo por quilo da preparação = soma do custo dos ingredientes / rendimento.
    """

    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint("yield_weight_g > 0", name="yield_weight_positive"),
        CheckConstraint("yield_portions IS NULL OR yield_portions > 0", name="yield_portions_positive"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    yield_weight_g: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    yield_portions: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.position",
    )
    foods: Mapped[list["Food"]] = relationship(back_populates="recipe")


class RecipeIngredient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ingrediente de uma ficha técnica.

    ``gross_quantity`` é a quantidade bruta (como comprada), na unidade do
    ingrediente, e é a base do custo. ``net_quantity`` (opcional) é a quantidade
    após o pré-preparo, usada para o fator de correção (bruto / líquido).
    """

    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("recipe_id", "ingredient_id"),
        CheckConstraint("gross_quantity > 0", name="gross_quantity_positive"),
        CheckConstraint(
            "net_quantity IS NULL OR (net_quantity > 0 AND net_quantity <= gross_quantity)",
            name="net_quantity_valid",
        ),
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    gross_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    net_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    ingredient: Mapped["Ingredient"] = relationship(back_populates="recipe_items", lazy="joined")

    @property
    def ingredient_name(self) -> str:
        return self.ingredient.name

    @property
    def unit(self) -> IngredientUnit:
        return self.ingredient.unit

    @property
    def unit_cost(self) -> Decimal:
        return self.ingredient.unit_cost
