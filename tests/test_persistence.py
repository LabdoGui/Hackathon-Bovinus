import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError

from app.core.enums import IngredientUnit, ItemSource, TransactionStatus
from app.models import Food, Ingredient, Recipe, RecipeIngredient, Transaction, TransactionItem


def _recipe(session, name="Arroz") -> Recipe:
    ingredient = Ingredient(name=f"{name} cru", unit=IngredientUnit.KG, unit_cost=Decimal("6.5"))
    recipe = Recipe(name=name, yield_weight_g=Decimal("2600"))
    recipe.ingredients = [RecipeIngredient(ingredient=ingredient, gross_quantity=Decimal("1.0"))]
    session.add(recipe)
    session.commit()
    return recipe


def test_roundtrip_keeps_exact_decimals_and_utc(db_session):
    ingredient = Ingredient(name="Azeite", unit=IngredientUnit.LITER, unit_cost=Decimal("12345678.1234"))
    db_session.add(ingredient)
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.get(Ingredient, ingredient.id)
    assert loaded.unit_cost == Decimal("12345678.1234")
    assert isinstance(loaded.unit_cost, Decimal)
    assert loaded.unit is IngredientUnit.LITER
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset().total_seconds() == 0


def test_relationships_food_recipe_ingredients(db_session):
    recipe = _recipe(db_session)
    food = Food(name="Arroz branco", recognition_class="arroz_branco", recipe=recipe)
    db_session.add(food)
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.scalar(select(Food).where(Food.recognition_class == "arroz_branco"))
    assert loaded.recipe.name == "Arroz"
    assert loaded.recipe.ingredients[0].ingredient.name == "Arroz cru"
    assert loaded.recipe.ingredients[0].ingredient_name == "Arroz cru"


def test_unique_name_is_enforced(db_session):
    db_session.add(Ingredient(name="Sal", unit_cost=Decimal("1")))
    db_session.commit()
    db_session.add(Ingredient(name="Sal", unit_cost=Decimal("2")))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_check_constraint_rejects_negative_cost(db_session):
    db_session.add(Ingredient(name="Negativo", unit_cost=Decimal("-1")))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_keys_are_enforced_on_sqlite(db_session):
    recipe = Recipe(name="Sem ingrediente válido", yield_weight_g=Decimal("100"))
    db_session.add(recipe)
    db_session.flush()
    db_session.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=uuid.uuid4(), gross_quantity=Decimal("1")))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_recipe_cascades_to_its_ingredients(db_session):
    recipe = _recipe(db_session)
    db_session.delete(recipe)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(RecipeIngredient)) == 0
    assert db_session.scalar(select(func.count()).select_from(Ingredient)) == 1


def test_ingredient_in_use_cannot_be_deleted(db_session):
    recipe = _recipe(db_session)
    db_session.delete(recipe.ingredients[0].ingredient)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_transaction_with_items_and_json_fields(db_session):
    transaction = Transaction(
        code="PC-TESTE-0001",
        status=TransactionStatus.PENDING_REVIEW,
        gross_weight_g=Decimal("650.0"),
        tare_g=Decimal("150.0"),
        net_weight_g=Decimal("500.0"),
        price_per_kg=Decimal("69.90"),
        charged_amount=Decimal("34.95"),
        requires_review=True,
        review_reasons=["baixa_confianca"],
    )
    transaction.items = [
        TransactionItem(
            food_name="Arroz", source=ItemSource.RECOGNITION, proportion=Decimal("0.6"), weight_g=Decimal("300")
        ),
        TransactionItem(
            food_name="Feijão",
            source=ItemSource.RECOGNITION,
            proportion=Decimal("0.4"),
            weight_g=Decimal("200"),
            position=1,
        ),
    ]
    db_session.add(transaction)
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.scalar(select(Transaction).where(Transaction.code == "PC-TESTE-0001"))
    assert loaded.review_reasons == ["baixa_confianca"]
    assert [item.food_name for item in loaded.items] == ["Arroz", "Feijão"]
    assert sum(item.weight_g for item in loaded.items) == loaded.net_weight_g

    db_session.delete(loaded)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(TransactionItem)) == 0


def test_proportion_out_of_range_is_rejected(db_session):
    transaction = Transaction(
        code="PC-TESTE-0002",
        gross_weight_g=Decimal("100"),
        net_weight_g=Decimal("100"),
        price_per_kg=Decimal("1"),
        charged_amount=Decimal("0.1"),
    )
    transaction.items = [
        TransactionItem(food_name="X", source=ItemSource.MANUAL, proportion=Decimal("1.5"), weight_g=Decimal("1"))
    ]
    db_session.add(transaction)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_duplicate_idempotency_key_is_rejected(db_session):
    common = dict(gross_weight_g=Decimal("1"), net_weight_g=Decimal("1"), price_per_kg=Decimal("1"), charged_amount=0)
    db_session.add(Transaction(code="A", idempotency_key="chave-1", **common))
    db_session.commit()
    db_session.add(Transaction(code="B", idempotency_key="chave-1", **common))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_naive_datetime_is_rejected(db_session):
    transaction = Transaction(
        code="C",
        gross_weight_g=Decimal("1"),
        net_weight_g=Decimal("1"),
        price_per_kg=Decimal("1"),
        charged_amount=Decimal("0"),
        confirmed_at=datetime(2026, 1, 1, 12, 0),
    )
    db_session.add(transaction)
    with pytest.raises(StatementError):
        db_session.commit()
