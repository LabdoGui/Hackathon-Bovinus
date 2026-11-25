import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.enums import AuditAction, ScaleMode
from app.database.seed import seed_demo_data
from app.models import AuditLog, Food, ScaleReading, Transaction


@pytest.fixture
def foods(app):
    with app.state.db.session_scope() as session:
        seed_demo_data(session)
        return {f.recognition_class: str(f.id) for f in session.scalars(select(Food))}


def _reading(client, gross=650, tare=150) -> str:
    body = client.post("/api/v1/scale/readings", json={"simulated_weight_g": gross, "tare_g": tare}).json()
    assert body["valid_for_transaction"], body
    return body["id"]


def _payload(reading_id, foods, items=None, **extra):
    items = items or [("arroz_branco", 0.6), ("feijao_carioca", 0.4)]
    return {
        "scale_reading_id": reading_id,
        "items": [{"food_id": foods[cls], "proportion": p} for cls, p in items],
        **extra,
    }


def test_create_transaction_full_calculation(client, foods):
    rice_cost = client.get(
        f"/api/v1/recipes/{client.get(f'/api/v1/foods/{foods['arroz_branco']}').json()['recipe_id']}/cost"
    ).json()["cost_per_kg"]

    response = client.post("/api/v1/transactions", json=_payload(_reading(client), foods))
    assert response.status_code == 201, response.text
    tx = response.json()

    assert tx["code"].startswith("PC-")
    assert tx["status"] == "confirmed" and tx["confirmed_at"] is not None
    assert tx["requires_review"] is False and tx["review_reasons"] == []
    assert (tx["gross_weight_g"], tx["tare_g"], tx["net_weight_g"]) == (650.0, 150.0, 500.0)
    weights = [item["weight_g"] for item in tx["items"]]
    assert weights == [300.0, 200.0]
    assert sum(Decimal(str(w)) for w in weights) == Decimal("500.0")

    assert tx["items"][0]["cost_per_kg"] == rice_cost
    assert tx["price_per_kg"] == 59.9
    assert tx["charged_amount"] == 29.95
    food_cost = sum(Decimal(str(i["cost"])) for i in tx["items"])
    assert Decimal(str(tx["food_cost"])) == food_cost
    assert Decimal(str(tx["gross_margin"])) == Decimal("29.95") - food_cost
    expected_pct = ((Decimal("29.95") - food_cost) * 100 / Decimal("29.95")).quantize(Decimal("0.01"))
    assert Decimal(str(tx["gross_margin_pct"])) == expected_pct


def test_food_without_recipe_goes_to_review(client, foods):
    payload = _payload(_reading(client), foods, items=[("arroz_branco", 0.7), ("sobremesa_do_dia", 0.3)])
    tx = client.post("/api/v1/transactions", json=payload).json()
    assert tx["status"] == "pending_review"
    assert tx["review_reasons"] == ["custo_indisponivel"]
    assert tx["food_cost"] is None and tx["gross_margin"] is None
    assert tx["charged_amount"] == 29.95
    assert tx["items"][1]["cost"] is None


def test_inactive_food_goes_to_review(client, foods, manager_headers):
    client.patch(f"/api/v1/foods/{foods['feijao_carioca']}", json={"active": False}, headers=manager_headers)
    tx = client.post("/api/v1/transactions", json=_payload(_reading(client), foods)).json()
    assert tx["review_reasons"] == ["alimento_inativo"]


def test_price_override(client, foods):
    tx = client.post("/api/v1/transactions", json=_payload(_reading(client), foods, price_per_kg=80)).json()
    assert tx["price_per_kg"] == 80.0 and tx["charged_amount"] == 40.0


def test_reading_cannot_be_reused(client, foods):
    reading = _reading(client)
    assert client.post("/api/v1/transactions", json=_payload(reading, foods)).status_code == 201
    second = client.post("/api/v1/transactions", json=_payload(reading, foods, price_per_kg=70))
    assert second.status_code == 409


def test_idempotency_key(client, foods, db_session):
    payload = _payload(_reading(client), foods)
    headers = {"Idempotency-Key": "balcao1-000123"}
    first = client.post("/api/v1/transactions", json=payload, headers=headers)
    replay = client.post("/api/v1/transactions", json=payload, headers=headers)
    assert first.status_code == 201 and replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 1

    other = client.post("/api/v1/transactions", json={**payload, "price_per_kg": 10}, headers=headers)
    assert other.status_code == 409


def test_invalid_idempotency_key_format(client, foods):
    response = client.post(
        "/api/v1/transactions", json=_payload(_reading(client), foods), headers={"Idempotency-Key": "a b"}
    )
    assert response.status_code == 422


def _insert_reading(app, **fields) -> str:
    base = dict(mode=ScaleMode.MOCK, gross_weight_g=Decimal("650"), tare_g=Decimal("150"), net_weight_g=Decimal("500"), stable=True)
    with app.state.db.session_scope() as session:
        reading = ScaleReading(**{**base, **fields})
        session.add(reading)
        session.flush()
        return str(reading.id)


@pytest.mark.parametrize(
    ("fields", "fragment"),
    [
        ({"stable": False}, "instável"),
        ({"gross_weight_g": Decimal("155"), "net_weight_g": Decimal("5")}, "mínimo"),
        ({"created_at": datetime.now(UTC) - timedelta(hours=1)}, "expirada"),
        ({"gross_weight_g": None, "net_weight_g": None, "error": "Falha na balança"}, "Falha"),
    ],
)
def test_invalid_readings_are_rejected(app, client, foods, fields, fragment):
    reading = _insert_reading(app, **fields)
    response = client.post("/api/v1/transactions", json=_payload(reading, foods))
    assert response.status_code == 422
    assert any(fragment in issue for issue in response.json()["error"]["details"]["issues"])


def test_unknown_reading_and_food(client, foods):
    assert client.post("/api/v1/transactions", json=_payload(str(uuid.uuid4()), foods)).status_code == 422
    payload = _payload(_reading(client), foods)
    payload["items"][0]["food_id"] = str(uuid.uuid4())
    response = client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violation"


@pytest.mark.parametrize(
    "items",
    [
        [("arroz_branco", 0.5), ("feijao_carioca", 0.3)],
        [("arroz_branco", 0.5), ("arroz_branco", 0.5)],
        [("arroz_branco", 0)],
    ],
)
def test_invalid_items(client, foods, items):
    assert client.post("/api/v1/transactions", json=_payload(_reading(client), foods, items=items)).status_code == 422


def test_missing_default_price(app, settings, client, foods):
    settings.default_price_per_kg = None
    response = client.post("/api/v1/transactions", json=_payload(_reading(client), foods))
    assert response.status_code == 422
    assert "DEFAULT_PRICE_PER_KG" in response.json()["error"]["message"]


def test_preview_does_not_persist(client, foods, db_session):
    response = client.post(
        "/api/v1/transactions/preview",
        json={
            "gross_weight_g": 650,
            "tare_g": 150,
            "items": [{"food_id": foods["arroz_branco"], "proportion": 1 / 3}, {"food_id": foods["farofa"], "proportion": 2 / 3}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["net_weight_g"] == 500.0
    assert sum(Decimal(str(i["weight_g"])) for i in body["items"]) == Decimal("500.0")
    assert body["cost_complete"] is True
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_preview_tare_greater_than_gross(client, foods):
    response = client.post(
        "/api/v1/transactions/preview",
        json={"gross_weight_g": 100, "tare_g": 200, "items": [{"food_id": foods["arroz_branco"], "proportion": 1}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "calculation_error"


def test_list_get_and_filters(client, foods):
    client.post("/api/v1/transactions", json=_payload(_reading(client), foods))
    client.post(
        "/api/v1/transactions",
        json=_payload(_reading(client), foods, items=[("sobremesa_do_dia", 1)]),
    )
    assert client.get("/api/v1/transactions").json()["total"] == 2
    assert client.get("/api/v1/transactions", params={"status": "pending_review"}).json()["total"] == 1
    assert client.get("/api/v1/transactions", params={"requires_review": False}).json()["total"] == 1
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert client.get("/api/v1/transactions", params={"created_from": future}).json()["total"] == 0
    tx_id = client.get("/api/v1/transactions").json()["items"][0]["id"]
    assert client.get(f"/api/v1/transactions/{tx_id}").status_code == 200
    assert client.get(f"/api/v1/transactions/{uuid.uuid4()}").status_code == 404


def test_cancel_transaction(client, foods, operator_headers, manager_headers, db_session):
    tx = client.post("/api/v1/transactions", json=_payload(_reading(client), foods)).json()
    url = f"/api/v1/transactions/{tx['id']}/cancel"
    assert client.post(url, json={"reason": "Prato devolvido"}, headers=operator_headers).status_code == 403
    cancelled = client.post(url, json={"reason": "Prato devolvido"}, headers=manager_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["cancelled_at"] is not None
    assert client.post(url, json={"reason": "De novo"}, headers=manager_headers).status_code == 409

    actions = db_session.scalars(
        select(AuditLog.action).where(AuditLog.entity_type == "transaction", AuditLog.entity_id == tx["id"])
    ).all()
    assert actions == [AuditAction.CREATE, AuditAction.STATUS_CHANGE]


def test_recipe_cost_endpoint(client, foods):
    recipe_id = client.get(f"/api/v1/foods/{foods['arroz_branco']}").json()["recipe_id"]
    body = client.get(f"/api/v1/recipes/{recipe_id}/cost").json()
    assert body["total_cost"] == 7.715
    assert body["cost_per_kg"] == 2.9673
    assert body["is_demo"] is True
    garlic = next(i for i in body["ingredients"] if i["ingredient_name"].startswith("Alho"))
    assert garlic["cost"] == 0.64
    assert garlic["correction_factor"] == 1.1765  # 0,02 / 0,017
