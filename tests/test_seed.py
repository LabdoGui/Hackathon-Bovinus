from sqlalchemy import func, select

from app.database.seed import DEMO_FOODS, DEMO_INGREDIENTS, DEMO_RECIPES, seed_demo_data
from app.models import AuditLog, Food, Ingredient, Recipe


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_seed_is_idempotent(db_session):
    first = seed_demo_data(db_session)
    assert first.created == {
        "ingredients": len(DEMO_INGREDIENTS),
        "recipes": len(DEMO_RECIPES),
        "foods": len(DEMO_FOODS),
    }
    counts = (_count(db_session, Ingredient), _count(db_session, Recipe), _count(db_session, Food))
    audit_count = _count(db_session, AuditLog)

    second = seed_demo_data(db_session)
    assert second.created == {"ingredients": 0, "recipes": 0, "foods": 0}
    assert (_count(db_session, Ingredient), _count(db_session, Recipe), _count(db_session, Food)) == counts
    assert _count(db_session, AuditLog) == audit_count


def test_seed_data_is_clearly_marked_as_fictitious(db_session):
    seed_demo_data(db_session)
    for model in (Ingredient, Recipe, Food):
        for entity in db_session.scalars(select(model)):
            assert entity.is_demo is True
            assert "(demo)" in entity.name


def test_seed_includes_food_without_recipe(db_session):
    seed_demo_data(db_session)
    food = db_session.scalar(select(Food).where(Food.recognition_class == "sobremesa_do_dia"))
    assert food is not None and food.recipe_id is None


def test_seed_does_not_override_existing_records(db_session):
    db_session.add(Food(name="Meu arroz", recognition_class="arroz_branco"))
    db_session.commit()
    report = seed_demo_data(db_session)
    assert report.skipped["foods"] == 1
    assert db_session.scalar(select(Food).where(Food.recognition_class == "arroz_branco")).name == "Meu arroz"


def test_seed_via_api_listing(client, app):
    with app.state.db.session_scope() as session:
        seed_demo_data(session)
    body = client.get("/api/v1/recipes", params={"limit": 200}).json()
    assert body["total"] == len(DEMO_RECIPES)
    assert all(recipe["is_demo"] for recipe in body["items"])
