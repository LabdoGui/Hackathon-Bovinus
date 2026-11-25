"""Regras de negócio do cadastro: ingredientes, fichas técnicas e alimentos."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AuditAction
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import Food, Ingredient, Operator, Recipe, RecipeIngredient
from app.repositories.catalog import FoodRepository, IngredientRepository, RecipeRepository
from app.schemas.food import FoodCreate, FoodUpdate
from app.schemas.ingredient import IngredientCreate, IngredientUpdate
from app.schemas.recipe import RecipeCreate, RecipeIngredientIn, RecipeUpdate
from app.services.audit import AuditService
from app.utils.serialization import entity_snapshot


def _operator_id(operator: Operator | None) -> uuid.UUID | None:
    return operator.id if operator is not None else None


def _reject_nulls(changes: dict[str, Any], nullable: Iterable[str]) -> None:
    allowed = set(nullable)
    invalid = sorted(key for key, value in changes.items() if value is None and key not in allowed)
    if invalid:
        raise BusinessRuleError("Campos obrigatórios não podem ser nulos.", details={"fields": invalid})


class _CatalogService:
    entity_type: str

    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditService(session)

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Operação viola uma restrição de unicidade ou integridade.") from exc


class IngredientService(_CatalogService):
    entity_type = "ingredient"

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = IngredientRepository(session)

    def get(self, ingredient_id: uuid.UUID) -> Ingredient:
        ingredient = self.repository.get(ingredient_id)
        if ingredient is None:
            raise NotFoundError("Ingrediente não encontrado.")
        return ingredient

    def list(self, **filters: Any) -> tuple[list[Ingredient], int]:
        return self.repository.list(**filters)

    def create(self, data: IngredientCreate, operator: Operator | None) -> Ingredient:
        if self.repository.get_by_name(data.name):
            raise ConflictError(f"Já existe um ingrediente chamado '{data.name}'.")
        ingredient = self.repository.add(Ingredient(**data.model_dump()))
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=ingredient.id,
            action=AuditAction.CREATE,
            operator_id=_operator_id(operator),
            after=entity_snapshot(ingredient),
        )
        self._commit()
        return ingredient

    def update(self, ingredient_id: uuid.UUID, data: IngredientUpdate, operator: Operator | None) -> Ingredient:
        ingredient = self.get(ingredient_id)
        changes = data.model_dump(exclude_unset=True)
        _reject_nulls(changes, nullable={"notes"})
        if "name" in changes and changes["name"] != ingredient.name and self.repository.get_by_name(changes["name"]):
            raise ConflictError(f"Já existe um ingrediente chamado '{changes['name']}'.")
        before = entity_snapshot(ingredient)
        for key, value in changes.items():
            setattr(ingredient, key, value)
        self.session.flush()
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=ingredient.id,
            action=AuditAction.UPDATE,
            operator_id=_operator_id(operator),
            before=before,
            after=entity_snapshot(ingredient),
        )
        self._commit()
        return ingredient

    def delete(self, ingredient_id: uuid.UUID, operator: Operator | None) -> None:
        ingredient = self.get(ingredient_id)
        if self.repository.is_used_in_recipes(ingredient.id):
            raise ConflictError("Ingrediente usado em fichas técnicas. Desative-o (active=false) em vez de excluir.")
        before = entity_snapshot(ingredient)
        self.repository.delete(ingredient)
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=ingredient_id,
            action=AuditAction.DELETE,
            operator_id=_operator_id(operator),
            before=before,
        )
        self._commit()


class RecipeService(_CatalogService):
    entity_type = "recipe"

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = RecipeRepository(session)
        self.ingredients = IngredientRepository(session)

    def get(self, recipe_id: uuid.UUID) -> Recipe:
        recipe = self.repository.get(recipe_id)
        if recipe is None:
            raise NotFoundError("Ficha técnica não encontrada.")
        return recipe

    def list(self, **filters: Any) -> tuple[list[Recipe], int]:
        return self.repository.list(**filters)

    @staticmethod
    def snapshot(recipe: Recipe) -> dict[str, Any]:
        data = entity_snapshot(recipe)
        data["ingredients"] = [
            entity_snapshot(item, exclude=("id", "recipe_id", "created_at", "updated_at")) for item in recipe.ingredients
        ]
        return data

    def _resolve_ingredients(self, items: list[RecipeIngredientIn]) -> dict[uuid.UUID, Ingredient]:
        found = self.ingredients.get_many(item.ingredient_id for item in items)
        missing = [str(item.ingredient_id) for item in items if item.ingredient_id not in found]
        if missing:
            raise BusinessRuleError("Ingredientes inexistentes na ficha técnica.", details={"ingredient_ids": missing})
        return found

    @staticmethod
    def _build_items(items: list[RecipeIngredientIn], found: dict[uuid.UUID, Ingredient]) -> list[RecipeIngredient]:
        return [
            RecipeIngredient(
                ingredient=found[item.ingredient_id],
                gross_quantity=item.gross_quantity,
                net_quantity=item.net_quantity,
                position=index,
            )
            for index, item in enumerate(items)
        ]

    def create(self, data: RecipeCreate, operator: Operator | None) -> Recipe:
        if self.repository.get_by_name(data.name):
            raise ConflictError(f"Já existe uma ficha técnica chamada '{data.name}'.")
        recipe = Recipe(**data.model_dump(exclude={"ingredients"}))
        recipe.ingredients = self._build_items(data.ingredients, self._resolve_ingredients(data.ingredients))
        self.repository.add(recipe)
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=recipe.id,
            action=AuditAction.CREATE,
            operator_id=_operator_id(operator),
            after=self.snapshot(recipe),
        )
        self._commit()
        return self.get(recipe.id)

    def update(self, recipe_id: uuid.UUID, data: RecipeUpdate, operator: Operator | None) -> Recipe:
        recipe = self.get(recipe_id)
        changes = data.model_dump(exclude_unset=True, exclude={"ingredients"})
        _reject_nulls(changes, nullable={"description", "yield_portions"})
        if "ingredients" in data.model_fields_set and data.ingredients is None:
            raise BusinessRuleError("Campos obrigatórios não podem ser nulos.", details={"fields": ["ingredients"]})
        if "name" in changes and changes["name"] != recipe.name and self.repository.get_by_name(changes["name"]):
            raise ConflictError(f"Já existe uma ficha técnica chamada '{changes['name']}'.")
        found = self._resolve_ingredients(data.ingredients) if data.ingredients is not None else None
        before = self.snapshot(recipe)
        for key, value in changes.items():
            setattr(recipe, key, value)
        if data.ingredients is not None and found is not None:
            recipe.ingredients.clear()
            self.session.flush()  # remove os itens antigos antes de inserir os novos (restrição única)
            recipe.ingredients.extend(self._build_items(data.ingredients, found))
        self.session.flush()
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=recipe.id,
            action=AuditAction.UPDATE,
            operator_id=_operator_id(operator),
            before=before,
            after=self.snapshot(recipe),
        )
        self._commit()
        self.session.expire(recipe)
        return self.get(recipe.id)

    def delete(self, recipe_id: uuid.UUID, operator: Operator | None) -> None:
        recipe = self.get(recipe_id)
        if self.repository.is_used_by_foods(recipe.id):
            raise ConflictError("Ficha técnica vinculada a alimentos. Desvincule-os ou desative a ficha (active=false).")
        before = self.snapshot(recipe)
        self.repository.delete(recipe)
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=recipe_id,
            action=AuditAction.DELETE,
            operator_id=_operator_id(operator),
            before=before,
        )
        self._commit()


class FoodService(_CatalogService):
    entity_type = "food"

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = FoodRepository(session)
        self.recipes = RecipeRepository(session)

    def get(self, food_id: uuid.UUID) -> Food:
        food = self.repository.get(food_id)
        if food is None:
            raise NotFoundError("Alimento não encontrado.")
        return food

    def list(self, **filters: Any) -> tuple[list[Food], int]:
        return self.repository.list(**filters)

    def _check_unique(self, *, name: str | None, recognition_class: str | None, current: Food | None) -> None:
        if name is not None and (existing := self.repository.get_by_name(name)) and existing is not current:
            raise ConflictError(f"Já existe um alimento chamado '{name}'.")
        if (
            recognition_class is not None
            and (existing := self.repository.get_by_recognition_class(recognition_class))
            and existing is not current
        ):
            raise ConflictError(f"A classe de reconhecimento '{recognition_class}' já está em uso.")

    def _check_recipe(self, recipe_id: uuid.UUID | None) -> None:
        if recipe_id is not None and self.recipes.get(recipe_id) is None:
            raise BusinessRuleError("Ficha técnica informada não existe.", details={"recipe_id": str(recipe_id)})

    def create(self, data: FoodCreate, operator: Operator | None) -> Food:
        self._check_unique(name=data.name, recognition_class=data.recognition_class, current=None)
        self._check_recipe(data.recipe_id)
        food = self.repository.add(Food(**data.model_dump()))
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=food.id,
            action=AuditAction.CREATE,
            operator_id=_operator_id(operator),
            after=entity_snapshot(food),
        )
        self._commit()
        self.session.refresh(food)
        return food

    def update(self, food_id: uuid.UUID, data: FoodUpdate, operator: Operator | None) -> Food:
        food = self.get(food_id)
        changes = data.model_dump(exclude_unset=True)
        _reject_nulls(changes, nullable={"category", "description", "recipe_id"})
        self._check_unique(name=changes.get("name"), recognition_class=changes.get("recognition_class"), current=food)
        if "recipe_id" in changes:
            self._check_recipe(changes["recipe_id"])
        before = entity_snapshot(food)
        for key, value in changes.items():
            setattr(food, key, value)
        self.session.flush()
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=food.id,
            action=AuditAction.UPDATE,
            operator_id=_operator_id(operator),
            before=before,
            after=entity_snapshot(food),
        )
        self._commit()
        self.session.refresh(food)
        return food

    def delete(self, food_id: uuid.UUID, operator: Operator | None) -> None:
        food = self.get(food_id)
        if self.repository.is_used_in_transactions(food.id):
            raise ConflictError("Alimento presente em transações. Desative-o (active=false) em vez de excluir.")
        before = entity_snapshot(food)
        self.repository.delete(food)
        self.audit.record(
            entity_type=self.entity_type,
            entity_id=food_id,
            action=AuditAction.DELETE,
            operator_id=_operator_id(operator),
            before=before,
        )
        self._commit()
