import uuid

import pytest
from sqlalchemy import select

from app.core.enums import AuditAction
from app.models import AuditLog


@pytest.fixture
def headers(manager_headers):
    return manager_headers


def _ingredient(client, headers, name="Arroz cru", unit_cost=6.5, unit="kg"):
    response = client.post(
        "/api/v1/ingredients", json={"name": name, "unit": unit, "unit_cost": unit_cost}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _recipe(client, headers, name="Arroz branco", ingredients=None):
    if ingredients is None:
        ingredients = [{"ingredient_id": _ingredient(client, headers)["id"], "gross_quantity": 1}]
    response = client.post(
        "/api/v1/recipes", json={"name": name, "yield_weight_g": 2600, "ingredients": ingredients}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# ----------------------------------------------------------------- ingredientes


def test_ingredient_crud(client, headers):
    created = _ingredient(client, headers, unit_cost="6.555")
    assert created["unit_cost"] == 6.555
    ingredient_id = created["id"]

    assert client.get(f"/api/v1/ingredients/{ingredient_id}").json()["name"] == "Arroz cru"

    updated = client.patch(f"/api/v1/ingredients/{ingredient_id}", json={"unit_cost": 7}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["unit_cost"] == 7.0

    listing = client.get("/api/v1/ingredients", params={"q": "arroz"}).json()
    assert listing["total"] == 1

    assert client.delete(f"/api/v1/ingredients/{ingredient_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/ingredients/{ingredient_id}").status_code == 404


def test_ingredient_duplicate_name_conflict(client, headers):
    _ingredient(client, headers)
    response = client.post("/api/v1/ingredients", json={"name": "Arroz cru", "unit_cost": 1}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "unit_cost": 1},
        {"name": "X", "unit_cost": -1},
        {"name": "X", "unit_cost": 1, "unit": "tonelada"},
        {"name": "X", "unit_cost": "NaN"},
    ],
)
def test_ingredient_validation(client, headers, payload):
    response = client.post("/api/v1/ingredients", json=payload, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_cannot_set_required_field_to_null(client, headers):
    ingredient = _ingredient(client, headers)
    response = client.patch(f"/api/v1/ingredients/{ingredient['id']}", json={"unit_cost": None}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"fields": ["unit_cost"]}


def test_ingredient_used_in_recipe_cannot_be_deleted(client, headers):
    recipe = _recipe(client, headers)
    ingredient_id = recipe["ingredients"][0]["ingredient_id"]
    response = client.delete(f"/api/v1/ingredients/{ingredient_id}", headers=headers)
    assert response.status_code == 409


def test_invalid_uuid_returns_422(client):
    assert client.get("/api/v1/ingredients/nao-e-uuid").status_code == 422


# ------------------------------------------------------------- fichas técnicas


def test_recipe_create_and_read_with_ingredients(client, headers):
    rice = _ingredient(client, headers)
    oil = _ingredient(client, headers, name="Óleo", unit="l", unit_cost=8.5)
    recipe = _recipe(
        client,
        headers,
        ingredients=[
            {"ingredient_id": rice["id"], "gross_quantity": 1, "net_quantity": 0.95},
            {"ingredient_id": oil["id"], "gross_quantity": 0.03},
        ],
    )
    assert recipe["yield_weight_g"] == 2600.0
    assert [i["ingredient_name"] for i in recipe["ingredients"]] == ["Arroz cru", "Óleo"]
    assert recipe["ingredients"][1]["unit"] == "l"
    assert recipe["ingredients"][1]["unit_cost"] == 8.5
    assert client.get(f"/api/v1/recipes/{recipe['id']}").json() == recipe


def test_recipe_rejects_duplicate_ingredient(client, headers):
    rice = _ingredient(client, headers)
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": "Duplicada",
            "yield_weight_g": 100,
            "ingredients": [
                {"ingredient_id": rice["id"], "gross_quantity": 1},
                {"ingredient_id": rice["id"], "gross_quantity": 2},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_recipe_rejects_unknown_ingredient(client, headers):
    response = client.post(
        "/api/v1/recipes",
        json={"name": "X", "yield_weight_g": 100, "ingredients": [{"ingredient_id": str(uuid.uuid4()), "gross_quantity": 1}]},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violation"


@pytest.mark.parametrize(
    "changes",
    [{"yield_weight_g": 0}, {"ingredients": []}, {"yield_portions": 0}],
)
def test_recipe_update_validation(client, headers, changes):
    recipe = _recipe(client, headers)
    assert client.patch(f"/api/v1/recipes/{recipe['id']}", json=changes, headers=headers).status_code == 422


def test_recipe_net_quantity_cannot_exceed_gross(client, headers):
    rice = _ingredient(client, headers)
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": "X",
            "yield_weight_g": 100,
            "ingredients": [{"ingredient_id": rice["id"], "gross_quantity": 1, "net_quantity": 2}],
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_recipe_update_replaces_ingredients(client, headers):
    recipe = _recipe(client, headers)
    first_id = recipe["ingredients"][0]["ingredient_id"]
    beans = _ingredient(client, headers, name="Feijão", unit_cost=8.9)
    response = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={
            "yield_weight_g": 3000,
            "ingredients": [
                {"ingredient_id": beans["id"], "gross_quantity": 1},
                {"ingredient_id": first_id, "gross_quantity": 0.5},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["yield_weight_g"] == 3000.0
    assert [i["ingredient_name"] for i in body["ingredients"]] == ["Feijão", "Arroz cru"]
    assert body["ingredients"][1]["gross_quantity"] == 0.5


def test_recipe_linked_to_food_cannot_be_deleted(client, headers):
    recipe = _recipe(client, headers)
    client.post(
        "/api/v1/foods", json={"name": "Arroz", "recognition_class": "arroz", "recipe_id": recipe["id"]}, headers=headers
    )
    assert client.delete(f"/api/v1/recipes/{recipe['id']}", headers=headers).status_code == 409


def test_recipe_delete(client, headers):
    recipe = _recipe(client, headers)
    assert client.delete(f"/api/v1/recipes/{recipe['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/recipes/{recipe['id']}").status_code == 404


# ------------------------------------------------------------------- alimentos


def test_food_crud_with_recipe(client, headers):
    recipe = _recipe(client, headers)
    response = client.post(
        "/api/v1/foods",
        json={"name": "Arroz branco", "recognition_class": "  Arroz_Branco ", "category": "Acompanhamento", "recipe_id": recipe["id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    food = response.json()
    assert food["recognition_class"] == "arroz_branco"
    assert food["recipe"]["name"] == "Arroz branco"

    unlinked = client.patch(f"/api/v1/foods/{food['id']}", json={"recipe_id": None}, headers=headers).json()
    assert unlinked["recipe_id"] is None and unlinked["recipe"] is None

    assert client.delete(f"/api/v1/foods/{food['id']}", headers=headers).status_code == 204


@pytest.mark.parametrize("recognition_class", ["arroz branco", "arroz-branco", "", "ç"])
def test_food_invalid_recognition_class(client, headers, recognition_class):
    response = client.post("/api/v1/foods", json={"name": "X", "recognition_class": recognition_class}, headers=headers)
    assert response.status_code == 422


def test_food_duplicates(client, headers):
    client.post("/api/v1/foods", json={"name": "Arroz", "recognition_class": "arroz"}, headers=headers)
    same_class = client.post("/api/v1/foods", json={"name": "Outro", "recognition_class": "arroz"}, headers=headers)
    same_name = client.post("/api/v1/foods", json={"name": "Arroz", "recognition_class": "outro"}, headers=headers)
    assert same_class.status_code == 409
    assert same_name.status_code == 409


def test_food_with_unknown_recipe(client, headers):
    response = client.post(
        "/api/v1/foods", json={"name": "X", "recognition_class": "x", "recipe_id": str(uuid.uuid4())}, headers=headers
    )
    assert response.status_code == 422


def test_food_filters_and_pagination(client, headers):
    for index in range(5):
        client.post(
            "/api/v1/foods",
            json={"name": f"Item {index}", "recognition_class": f"item_{index}", "category": "A" if index % 2 else "B"},
            headers=headers,
        )
    client.patch(
        f"/api/v1/foods/{client.get('/api/v1/foods', params={'q': 'Item 0'}).json()['items'][0]['id']}",
        json={"active": False},
        headers=headers,
    )
    page = client.get("/api/v1/foods", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["limit"] == 2
    assert client.get("/api/v1/foods", params={"category": "A"}).json()["total"] == 2
    assert client.get("/api/v1/foods", params={"active": False}).json()["total"] == 1
    assert client.get("/api/v1/foods", params={"q": "item_3"}).json()["total"] == 1
    assert client.get("/api/v1/foods", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/v1/foods", params={"limit": 500}).status_code == 422


def test_catalog_changes_are_audited(client, headers, db_session):
    me = client.get("/api/v1/operators/me", headers=headers).json()
    ingredient = _ingredient(client, headers)
    client.patch(f"/api/v1/ingredients/{ingredient['id']}", json={"unit_cost": 9.99}, headers=headers)
    client.delete(f"/api/v1/ingredients/{ingredient['id']}", headers=headers)

    logs = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "ingredient", AuditLog.entity_id == ingredient["id"])
    ).all()
    assert [log.action for log in logs] == [AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE]
    assert all(str(log.operator_id) == me["id"] for log in logs)
    update = logs[1]
    assert update.before["unit_cost"] == "6.5000"
    assert update.after["unit_cost"] == "9.9900"
