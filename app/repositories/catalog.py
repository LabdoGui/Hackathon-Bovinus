from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models import Food, Ingredient, Recipe, RecipeIngredient, TransactionItem
from app.repositories.base import Repository


def _search(column, query: str):
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


class IngredientRepository(Repository[Ingredient]):
    model = Ingredient

    def get_by_name(self, name: str) -> Ingredient | None:
        return self.session.scalar(select(Ingredient).where(Ingredient.name == name))

    def get_many(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Ingredient]:
        ids = list(ids)
        if not ids:
            return {}
        return {item.id: item for item in self.session.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))}

    def list(self, *, query: str | None, active: bool | None, limit: int, offset: int) -> tuple[list[Ingredient], int]:
        statement = select(Ingredient)
        if query:
            statement = statement.where(_search(Ingredient.name, query))
        if active is not None:
            statement = statement.where(Ingredient.active.is_(active))
        return self.paginate(statement, limit=limit, offset=offset, order_by=[Ingredient.name])

    def is_used_in_recipes(self, ingredient_id: uuid.UUID) -> bool:
        return self.session.scalar(
            select(select(RecipeIngredient.id).where(RecipeIngredient.ingredient_id == ingredient_id).exists())
        ) or False


class RecipeRepository(Repository[Recipe]):
    model = Recipe

    def _with_ingredients(self):
        return select(Recipe).options(selectinload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))

    def get(self, entity_id: uuid.UUID) -> Recipe | None:
        return self.session.scalar(self._with_ingredients().where(Recipe.id == entity_id))

    def get_by_name(self, name: str) -> Recipe | None:
        return self.session.scalar(select(Recipe).where(Recipe.name == name))

    def list(self, *, query: str | None, active: bool | None, limit: int, offset: int) -> tuple[list[Recipe], int]:
        statement = self._with_ingredients()
        if query:
            statement = statement.where(_search(Recipe.name, query))
        if active is not None:
            statement = statement.where(Recipe.active.is_(active))
        return self.paginate(statement, limit=limit, offset=offset, order_by=[Recipe.name])

    def is_used_by_foods(self, recipe_id: uuid.UUID) -> bool:
        return self.session.scalar(select(select(Food.id).where(Food.recipe_id == recipe_id).exists())) or False


class FoodRepository(Repository[Food]):
    model = Food

    def get_by_name(self, name: str) -> Food | None:
        return self.session.scalar(select(Food).where(Food.name == name))

    def get_many(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Food]:
        ids = list(ids)
        if not ids:
            return {}
        statement = (
            select(Food)
            .where(Food.id.in_(ids))
            .options(selectinload(Food.recipe).selectinload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        )
        return {food.id: food for food in self.session.scalars(statement).unique()}

    def get_by_recognition_class(self, recognition_class: str) -> Food | None:
        return self.session.scalar(select(Food).where(Food.recognition_class == recognition_class))

    def list(
        self,
        *,
        query: str | None,
        active: bool | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Food], int]:
        statement = select(Food)
        if query:
            statement = statement.where(or_(_search(Food.name, query), _search(Food.recognition_class, query)))
        if active is not None:
            statement = statement.where(Food.active.is_(active))
        if category:
            statement = statement.where(Food.category == category)
        return self.paginate(statement, limit=limit, offset=offset, order_by=[Food.name])

    def is_used_in_transactions(self, food_id: uuid.UUID) -> bool:
        return self.session.scalar(
            select(
                select(TransactionItem.id)
                .where(or_(TransactionItem.food_id == food_id, TransactionItem.original_food_id == food_id))
                .exists()
            )
        ) or False
