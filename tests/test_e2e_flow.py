"""Fluxo completo do dia a dia, usando só a API (sem hardware): do cadastro ao relatório e ao backup."""

import io
from decimal import Decimal

import numpy as np
from alembic import command
from PIL import Image

from app.database.migrate import alembic_config
from app.services.recognition import MockFoodRecognitionService
from app.core.enums import MockScenario


def test_full_day_flow(client, app, settings, admin_headers, manager_headers, operator_headers):
    command.stamp(alembic_config(app.state.db.url), "head")
    app.state.recognition = MockFoodRecognitionService(MockScenario.CONFIDENT)
    settings.recognition_mock_requires_review = False

    # 1) cadastro (gerente): ingredientes -> ficha técnica -> alimentos
    def post(path, body, headers=manager_headers):
        response = client.post(f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()

    rice_in = post("/ingredients", {"name": "Arroz cru", "unit": "kg", "unit_cost": 6.0})
    oil_in = post("/ingredients", {"name": "Óleo", "unit": "l", "unit_cost": 9.0})
    recipe = post("/recipes", {
        "name": "Arroz da casa", "yield_weight_g": 2500,
        "ingredients": [{"ingredient_id": rice_in["id"], "gross_quantity": 1}, {"ingredient_id": oil_in["id"], "gross_quantity": 0.1}],
    })
    rice = post("/foods", {"name": "Arroz da casa", "recognition_class": "arroz_casa", "recipe_id": recipe["id"]})
    pudim = post("/foods", {"name": "Pudim", "recognition_class": "pudim"})  # sem ficha técnica
    assert client.get(f"/api/v1/recipes/{recipe['id']}/cost").json()["cost_per_kg"] == 2.76  # (6,00 + 0,90) / 2,5 kg

    # 2) pesagem + foto + reconhecimento (simulado) + transação
    photo = np.random.default_rng(3).random((720, 1280, 3)) * 255
    buffer = io.BytesIO()
    Image.fromarray(photo.astype("uint8")).save(buffer, format="JPEG")
    capture = client.post("/api/v1/camera/uploads", files={"file": ("prato.jpg", buffer.getvalue(), "image/jpeg")}).json()
    reading = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 650, "tare_g": 150}).json()
    assert reading["valid_for_transaction"] and reading["net_weight_g"] == 500.0
    result = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture["id"], "scale_reading_id": reading["id"]})
    assert result.status_code == 201 and result.json()["is_simulated"] is True

    # 3) venda direta sem reconhecimento: arroz + pudim (sem custo) -> revisão
    reading2 = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 650, "tare_g": 150}).json()
    tx = client.post("/api/v1/transactions", json={
        "scale_reading_id": reading2["id"],
        "items": [{"food_id": rice["id"], "proportion": 0.6}, {"food_id": pudim["id"], "proportion": 0.4}],
    }, headers={**operator_headers, "Idempotency-Key": "e2e-0001"})
    assert tx.status_code == 201 and tx.json()["status"] == "pending_review"
    tx = tx.json()
    assert tx["price_per_kg"] == 59.9 and tx["charged_amount"] == 29.95 and tx["food_cost"] is None

    # 4) revisão humana: o operador troca o pudim por arroz e confirma
    items = tx["items"]
    incoherent = client.post(f"/api/v1/transactions/{tx['id']}/review", headers=operator_headers, json={
        "reason": "Teste de coerência",
        "items": [{"item_id": items[0]["id"], "food_id": rice["id"], "weight_g": 300}],
    })
    assert incoherent.status_code == 422  # 300 g não fecha os 500 g de peso líquido
    ok = client.post(f"/api/v1/transactions/{tx['id']}/review", headers=operator_headers, json={
        "reason": "Era tudo arroz", "items": [{"item_id": items[0]["id"], "food_id": rice["id"], "weight_g": 500}], "confirm": True,
    })
    assert ok.status_code == 200, ok.text
    confirmed = ok.json()
    assert confirmed["status"] == "confirmed" and confirmed["food_cost"] == 1.38  # 0,5 kg × R$ 2,76
    assert [i["is_corrected"] for i in confirmed["items"]] == [True]

    # 5) gerente: relatório, histórico e exportação coerentes com o que aconteceu
    summary = client.get("/api/v1/reports/summary", headers=manager_headers).json()
    assert summary["transactions_confirmed"] == 1 and summary["transactions_pending_review"] == 0
    assert Decimal(str(summary["total_food_cost"])) == Decimal("1.38")
    history = client.get(f"/api/v1/transactions/{tx['id']}/history", headers=manager_headers).json()
    assert [h["action"] for h in history] == ["create", "correction", "status_change"]
    csv = client.get("/api/v1/reports/transactions.csv", headers=manager_headers)
    assert csv.status_code == 200 and tx["code"] in csv.content.decode("utf-8-sig")

    # 6) administrador: backup verificado, contendo a transação confirmada
    backup = client.post("/api/v1/admin/backups", headers=admin_headers)
    assert backup.status_code == 201 and backup.json()["integrity"] == "ok"
