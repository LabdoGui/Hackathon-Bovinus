"""Adaptação entre as entidades do banco e o motor de cálculo de custos."""

from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import IngredientUnit
from app.models import Food, Recipe
from app.services.calculations import RecipeCostLine, correction_factor, ingredient_line_cost, recipe_cost


@dataclass(frozen=True)
class IngredientCostLine:
    ingredient_id: str
    ingredient_name: str
    unit: IngredientUnit
    gross_quantity: Decimal
    net_quantity: Decimal | None
    correction_factor: Decimal | None
    unit_cost: Decimal
    cost: Decimal


@dataclass(frozen=True)
class RecipeCostBreakdown:
    recipe_id: str
    recipe_name: str
    is_demo: bool
    yield_weight_g: Decimal
    total_cost: Decimal
    cost_per_kg: Decimal
    ingredients: list[IngredientCostLine]


def recipe_cost_breakdown(recipe: Recipe) -> RecipeCostBreakdown:
    lines = []
    for item in recipe.ingredients:
        line = RecipeCostLine(gross_quantity=item.gross_quantity, unit_cost=item.ingredient.unit_cost)
        lines.append(
            IngredientCostLine(
                ingredient_id=str(item.ingredient_id),
                ingredient_name=item.ingredient.name,
                unit=item.ingredient.unit,
                gross_quantity=item.gross_quantity,
                net_quantity=item.net_quantity,
                correction_factor=correction_factor(item.gross_quantity, item.net_quantity),
                unit_cost=item.ingredient.unit_cost,
                cost=ingredient_line_cost(line),
            )
        )
    cost = recipe_cost(
        [RecipeCostLine(i.gross_quantity, i.ingredient.unit_cost) for i in recipe.ingredients], recipe.yield_weight_g
    )
    return RecipeCostBreakdown(
        recipe_id=str(recipe.id),
        recipe_name=recipe.name,
        is_demo=recipe.is_demo,
        yield_weight_g=recipe.yield_weight_g,
        total_cost=cost.total_cost,
        cost_per_kg=cost.cost_per_kg,
        ingredients=lines,
    )


def food_cost_per_kg(food: Food) -> Decimal | None:
    """Custo estimado por kg do alimento pronto; ``None`` se não houver ficha técnica."""
    if food.recipe is None or not food.recipe.ingredients:
        return None
    return recipe_cost_breakdown(food.recipe).cost_per_kg
