import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import IngredientUnit
from app.schemas.common import ORMModel
from app.schemas.types import LongText, Name, PositiveGrams, Quantity, UnitCost


class RecipeIngredientIn(BaseModel):
    ingredient_id: uuid.UUID
    gross_quantity: Quantity = Field(description="Quantidade bruta, na unidade do ingrediente (kg, l ou un).")
    net_quantity: Quantity | None = Field(
        default=None, description="Quantidade líquida após pré-preparo (opcional, para o fator de correção)."
    )

    @model_validator(mode="after")
    def _net_not_greater_than_gross(self) -> Self:
        if self.net_quantity is not None and self.net_quantity > self.gross_quantity:
            raise ValueError("net_quantity não pode ser maior que gross_quantity.")
        return self


def _ensure_unique_ingredients(items: list[RecipeIngredientIn] | None) -> None:
    if items is None:
        return
    ids = [item.ingredient_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Um ingrediente não pode aparecer duas vezes na mesma ficha técnica.")


class RecipeCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Arroz branco",
                    "yield_weight_g": 2600,
                    "ingredients": [
                        {"ingredient_id": "00000000-0000-0000-0000-000000000000", "gross_quantity": 1.0}
                    ],
                }
            ]
        }
    )

    name: Name
    description: LongText | None = None
    yield_weight_g: PositiveGrams = Field(description="Rendimento total da preparação pronta, em gramas.")
    yield_portions: int | None = Field(default=None, gt=0, le=100000)
    ingredients: list[RecipeIngredientIn] = Field(min_length=1, max_length=100)
    is_demo: bool = False
    active: bool = True

    @model_validator(mode="after")
    def _unique(self) -> Self:
        _ensure_unique_ingredients(self.ingredients)
        return self


class RecipeUpdate(BaseModel):
    name: Name | None = None
    description: LongText | None = None
    yield_weight_g: PositiveGrams | None = None
    yield_portions: int | None = Field(default=None, gt=0, le=100000)
    ingredients: list[RecipeIngredientIn] | None = Field(
        default=None, min_length=1, max_length=100, description="Se enviado, substitui todos os ingredientes."
    )
    is_demo: bool | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _unique(self) -> Self:
        _ensure_unique_ingredients(self.ingredients)
        return self


class RecipeIngredientRead(ORMModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_name: str
    unit: IngredientUnit
    unit_cost: UnitCost
    gross_quantity: Quantity
    net_quantity: Quantity | None
    position: int


class RecipeSummary(ORMModel):
    id: uuid.UUID
    name: str
    yield_weight_g: PositiveGrams
    is_demo: bool
    active: bool


class RecipeRead(RecipeSummary):
    description: str | None
    yield_portions: int | None
    ingredients: list[RecipeIngredientRead]
    created_at: datetime
    updated_at: datetime


class IngredientCostRead(BaseModel):
    ingredient_id: uuid.UUID
    ingredient_name: str
    unit: IngredientUnit
    gross_quantity: Quantity
    net_quantity: Quantity | None
    correction_factor: UnitCost | None = Field(description="Fator de correção = quantidade bruta / líquida.")
    unit_cost: UnitCost
    cost: UnitCost


class RecipeCostRead(BaseModel):
    recipe_id: uuid.UUID
    recipe_name: str
    is_demo: bool
    yield_weight_g: PositiveGrams
    total_cost: UnitCost = Field(description="Custo total dos ingredientes (quantidades brutas).")
    cost_per_kg: UnitCost = Field(description="Custo estimado por kg da preparação pronta.")
    ingredients: list[IngredientCostRead]
