import uuid
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.core.enums import AuditAction, MockScenario
from app.database.seed import seed_demo_data
from app.models import AuditLog, Food, TransactionItem
from app.services.calculations import calculate_plate_from_weights
from app.services.recognition import MockFoodRecognitionService


@pytest.fixture
def foods(app):
    with app.state.db.session_scope() as session:
        seed_demo_data(session)
        return {f.recognition_class: str(f.id) for f in session.scalars(select(Food))}


def _reading(client, gross=650, tare=150) -> str:
    return client.post("/api/v1/scale/readings", json={"simulated_weight_g": gross, "tare_g": tare}).json()["id"]


def _pending(client, foods, items=None, **extra):
    """Cria uma transação manual em revisão (inclui alimento sem ficha técnica)."""
    items = items or [("arroz_branco", 0.5), ("carne_de_panela", 0.3), ("sobremesa_do_dia", 0.2)]
    response = client.post(
        "/api/v1/transactions",
        json={"scale_reading_id": _reading(client), "items": [{"food_id": foods[c], "proportion": p} for c, p in items], **extra},
    )
    assert response.status_code == 201, response.text
    tx = response.json()
    assert tx["status"] == "pending_review"
    return tx


def _review(client, tx, headers, **body):
    return client.post(f"/api/v1/transactions/{tx['id']}/review", json=body, headers=headers)


def _item(tx, klass):
    return next(i for i in tx["items"] if i["recognition_class"] == klass)


# ----------------------------------------------------------------- permissões


def test_review_requires_authenticated_operator(client, foods, operator_headers):
    tx = _pending(client, foods)
    assert client.post(f"/api/v1/transactions/{tx['id']}/review", json={"reason": "ok", "confirm": True}).status_code == 401
    assert _review(client, tx, operator_headers, reason="Conferido no prato", confirm=True).status_code == 200


def test_review_payload_validation(client, foods, operator_headers):
    tx = _pending(client, foods)
    bad_bodies = [
        {"reason": "ok"},  # nada a fazer
        {"reason": "ab", "confirm": True},  # motivo curto
        {"reason": "Teste", "items": []},
        {"reason": "Teste", "items": [{"food_id": foods["arroz_branco"]}]},  # sem medida
        {"reason": "Teste", "items": [{"food_id": foods["arroz_branco"], "proportion": 0.5, "weight_g": 100}]},
        {"reason": "Teste", "items": [{"food_id": foods["arroz_branco"], "proportion": 0.5}, {"food_id": foods["farofa"], "weight_g": 100}]},
        {"reason": "Teste", "items": [{"food_id": foods["farofa"], "proportion": 0.5}, {"food_id": foods["farofa"], "proportion": 0.5}]},
        {"reason": "Teste", "items": [{"food_id": foods["farofa"], "proportion": 1.5}]},
    ]
    for body in bad_bodies:
        assert _review(client, tx, operator_headers, **body).status_code == 422, body


# ------------------------------------------------------------------ confirmar


def test_confirm_as_is_only_changes_status_and_audits(client, foods, operator_headers, db_session):
    tx = _pending(client, foods, items=[("arroz_branco", 0.6), ("sobremesa_do_dia", 0.4)])
    body = _review(client, tx, operator_headers, reason="Conferido visualmente", confirm=True).json()
    assert body["status"] == "confirmed" and body["requires_review"] is False and body["reviewed_by_id"]
    assert [i["is_corrected"] for i in body["items"]] == [False, False]
    assert [i["weight_g"] for i in body["items"]] == [i["weight_g"] for i in tx["items"]]
    actions = db_session.scalars(
        select(AuditLog.action).where(AuditLog.entity_id == tx["id"]).order_by(AuditLog.created_at)
    ).all()
    assert actions == [AuditAction.CREATE, AuditAction.STATUS_CHANGE]


def test_confirm_as_is_blocked_when_item_has_no_food(client, app, foods, operator_headers, settings):
    app.state.recognition = MockFoodRecognitionService(MockScenario.UNKNOWN_FOOD)
    import io
    import numpy as np
    from PIL import Image
    buffer = io.BytesIO()
    Image.fromarray((np.random.default_rng(1).random((720, 1280, 3)) * 255).astype("uint8")).save(buffer, format="JPEG")
    capture = client.post("/api/v1/camera/uploads", files={"file": ("p.jpg", buffer.getvalue(), "image/jpeg")}).json()["id"]
    reading = _reading(client)
    result = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture, "scale_reading_id": reading}).json()
    tx = client.post("/api/v1/transactions/from-recognition", json={"recognition_result_id": result["id"], "scale_reading_id": reading}).json()
    response = _review(client, tx, operator_headers, reason="Conferi", confirm=True)
    assert response.status_code == 422 and response.json()["error"]["code"] == "items_without_food"
    assert client.get(f"/api/v1/transactions/{tx['id']}").json()["status"] == "pending_review"


# ------------------------------------------------------------------- correções


def test_correct_food_and_weights_recalculates_cost_and_keeps_originals(client, foods, operator_headers, db_session):
    tx = _pending(client, foods)
    assert tx["food_cost"] is None and "custo_indisponivel" in tx["review_reasons"]
    rice, meat, dessert = (_item(tx, c) for c in ("arroz_branco", "carne_de_panela", "sobremesa_do_dia"))

    response = _review(
        client, tx, operator_headers,
        reason="Sobremesa era farofa; ajuste dos pesos",
        items=[
            {"item_id": rice["id"], "food_id": foods["arroz_branco"], "weight_g": 200},
            {"item_id": meat["id"], "food_id": foods["carne_de_panela"], "weight_g": 150},
            {"item_id": dessert["id"], "food_id": foods["farofa"], "weight_g": 150},
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending_review"  # corrigiu mas não confirmou
    assert [i["weight_g"] for i in body["items"]] == [200.0, 150.0, 150.0]
    assert sum(i["weight_g"] for i in body["items"]) == 500.0
    assert body["food_cost"] is not None and body["gross_margin"] is not None
    assert "custo_indisponivel" not in body["review_reasons"]

    fixed = _item(body, "sobremesa_do_dia")  # a classe reconhecida original permanece
    assert fixed["food_name"] == "Farofa simples (demo)" and fixed["is_corrected"] is True
    assert fixed["original_food_name"] == "Sobremesa do dia (demo)"
    assert fixed["original_food_id"] == foods["sobremesa_do_dia"]
    assert fixed["original_proportion"] == dessert["proportion"] and fixed["original_weight_g"] == dessert["weight_g"]
    assert fixed["cost"] is not None
    assert _item(body, "arroz_branco")["original_weight_g"] == 250.0  # 0,5 de 500 g

    # custo conferido contra o motor de cálculo
    costs = [i["cost_per_kg"] for i in body["items"]]
    expected = calculate_plate_from_weights(
        gross_weight_g=D("650"), tare_g=D("150"), price_per_kg=D("59.90"), weights_g=[D(200), D(150), D(150)],
        costs_per_kg=[D(str(c)) for c in costs],
    )
    assert D(str(body["food_cost"])) == expected.food_cost
    assert D(str(body["gross_margin"])) == expected.gross_margin


def test_correct_by_proportion(client, foods, operator_headers):
    tx = _pending(client, foods, items=[("arroz_branco", 0.5), ("sobremesa_do_dia", 0.5)])
    rice, dessert = _item(tx, "arroz_branco"), _item(tx, "sobremesa_do_dia")
    body = _review(
        client, tx, operator_headers, reason="Proporções erradas",
        items=[
            {"item_id": rice["id"], "food_id": foods["arroz_branco"], "proportion": 0.7},
            {"item_id": dessert["id"], "food_id": foods["farofa"], "proportion": 0.3},
        ],
    ).json()
    assert [i["proportion"] for i in body["items"]] == [0.7, 0.3]
    assert [i["weight_g"] for i in body["items"]] == [350.0, 150.0]
    assert body["items"][0]["original_proportion"] == 0.5 and body["items"][0]["is_corrected"]


def test_second_correction_never_overwrites_originals(client, foods, operator_headers):
    tx = _pending(client, foods, items=[("arroz_branco", 0.5), ("sobremesa_do_dia", 0.5)])
    a, b = _item(tx, "arroz_branco"), _item(tx, "sobremesa_do_dia")
    first = _review(client, tx, operator_headers, reason="Primeira", items=[
        {"item_id": a["id"], "food_id": foods["arroz_branco"], "weight_g": 300},
        {"item_id": b["id"], "food_id": foods["sobremesa_do_dia"], "weight_g": 200}]).json()
    second = _review(client, tx, operator_headers, reason="Segunda", items=[
        {"item_id": a["id"], "food_id": foods["arroz_branco"], "weight_g": 100},
        {"item_id": b["id"], "food_id": foods["sobremesa_do_dia"], "weight_g": 400}]).json()
    assert [i["weight_g"] for i in second["items"]] == [100.0, 400.0]
    assert [i["original_weight_g"] for i in second["items"]] == [250.0, 250.0]
    assert [i["original_weight_g"] for i in first["items"]] == [250.0, 250.0]


def test_add_and_remove_items(client, foods, operator_headers, db_session):
    tx = _pending(client, foods)
    rice, meat, dessert = (_item(tx, c) for c in ("arroz_branco", "carne_de_panela", "sobremesa_do_dia"))
    body = _review(
        client, tx, operator_headers, reason="Removi sobremesa e acrescentei salada",
        items=[
            {"item_id": rice["id"], "food_id": foods["arroz_branco"], "weight_g": 250},
            {"item_id": meat["id"], "food_id": foods["carne_de_panela"], "weight_g": 150},
            {"food_id": foods["salada_verde"], "weight_g": 100},
        ],
    ).json()
    assert {i["recognition_class"] for i in body["items"]} == {"arroz_branco", "carne_de_panela", "salada_verde"}
    added = _item(body, "salada_verde")
    assert added["source"] == "manual" and added["is_corrected"] is True and added["original_food_id"] is None
    assert db_session.scalars(select(TransactionItem).where(TransactionItem.id == uuid.UUID(dessert["id"]))).first() is None
    assert body["food_cost"] is not None

    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == tx["id"], AuditLog.action == AuditAction.CORRECTION)
    ).one()
    assert sorted(c["type"] for c in audit.after["changes"]) == ["added", "removed"]
    removed = next(c for c in audit.after["changes"] if c["type"] == "removed")
    assert removed["food"] == "Sobremesa do dia (demo)"


def test_confirm_with_corrections_writes_audit_trail(client, foods, operator_headers, make_api_key, db_session):
    tx = _pending(client, foods)
    items = [
        {"item_id": _item(tx, "arroz_branco")["id"], "food_id": foods["arroz_branco"], "weight_g": 250},
        {"item_id": _item(tx, "carne_de_panela")["id"], "food_id": foods["carne_de_panela"], "weight_g": 150},
        {"item_id": _item(tx, "sobremesa_do_dia")["id"], "food_id": foods["farofa"], "weight_g": 100},
    ]
    body = _review(client, tx, operator_headers, reason="Era farofa", items=items, confirm=True).json()
    assert body["status"] == "confirmed" and body["requires_review"] is False
    assert body["confirmed_at"] and body["reviewed_at"] and body["reviewed_by_id"]

    logs = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "transaction", AuditLog.entity_id == tx["id"]).order_by(AuditLog.created_at)).all()
    assert [log.action for log in logs] == [AuditAction.CREATE, AuditAction.CORRECTION, AuditAction.STATUS_CHANGE]
    correction, status = logs[1], logs[2]
    assert correction.reason == "Era farofa" and str(correction.operator_id) == body["reviewed_by_id"]
    before_items = {i["recognition_class"]: i for i in correction.before["items"]}
    after_items = {i["recognition_class"]: i for i in correction.after["items"]}
    assert before_items["sobremesa_do_dia"]["food_name"] == "Sobremesa do dia (demo)"
    assert after_items["sobremesa_do_dia"]["food_name"] == "Farofa simples (demo)"
    assert correction.before["food_cost"] is None and correction.after["food_cost"] is not None
    assert status.before["status"] == "pending_review" and status.after["status"] == "confirmed"

    again = _review(client, tx, operator_headers, reason="De novo", confirm=True)
    assert again.status_code == 409 and again.json()["error"]["code"] == "transaction_not_reviewable"


def test_cancelled_transaction_cannot_be_reviewed(client, foods, operator_headers, manager_headers):
    tx = _pending(client, foods)
    client.post(f"/api/v1/transactions/{tx['id']}/cancel", json={"reason": "Cliente desistiu"}, headers=manager_headers)
    assert _review(client, tx, operator_headers, reason="Tentativa", confirm=True).status_code == 409


# ----------------------------------------------------------------- validações


def test_weights_must_match_net_within_tolerance(client, foods, operator_headers):
    tx = _pending(client, foods, items=[("arroz_branco", 0.5), ("sobremesa_do_dia", 0.5)])
    a, b = _item(tx, "arroz_branco"), _item(tx, "sobremesa_do_dia")

    def attempt(w1, w2):
        return _review(client, tx, operator_headers, reason="Ajuste", items=[
            {"item_id": a["id"], "food_id": foods["arroz_branco"], "weight_g": w1},
            {"item_id": b["id"], "food_id": foods["sobremesa_do_dia"], "weight_g": w2}])

    far = attempt(300, 300)
    assert far.status_code == 422 and far.json()["error"]["code"] == "weights_do_not_match_net"
    assert far.json()["error"]["details"]["net_weight_g"] == "500.0"
    near = attempt(252, 250)  # soma 502 g, dentro de max(5 g, 2%)
    assert near.status_code == 200
    assert sum(i["weight_g"] for i in near.json()["items"]) == 500.0  # reescalado ao peso líquido


def test_proportions_must_sum_one(client, foods, operator_headers):
    tx = _pending(client, foods, items=[("arroz_branco", 0.5), ("sobremesa_do_dia", 0.5)])
    a, b = _item(tx, "arroz_branco"), _item(tx, "sobremesa_do_dia")
    response = _review(client, tx, operator_headers, reason="Ajuste", items=[
        {"item_id": a["id"], "food_id": foods["arroz_branco"], "proportion": 0.5},
        {"item_id": b["id"], "food_id": foods["sobremesa_do_dia"], "proportion": 0.2}])
    assert response.status_code == 422 and response.json()["error"]["code"] == "proportions_do_not_sum_one"


def test_foreign_item_unknown_food_and_no_change(client, foods, operator_headers):
    tx = _pending(client, foods, items=[("arroz_branco", 0.5), ("sobremesa_do_dia", 0.5)])
    other = _pending(client, foods, items=[("sobremesa_do_dia", 1)])
    a, b = _item(tx, "arroz_branco"), _item(tx, "sobremesa_do_dia")
    foreign = _review(client, tx, operator_headers, reason="Teste", items=[{"item_id": other["items"][0]["id"], "food_id": foods["sobremesa_do_dia"], "proportion": 1}])
    assert foreign.status_code == 422 and "item_ids" in foreign.json()["error"]["details"]
    ghost = _review(client, tx, operator_headers, reason="Teste", items=[{"item_id": a["id"], "food_id": str(uuid.uuid4()), "proportion": 1}])
    assert ghost.status_code == 422 and "food_ids" in ghost.json()["error"]["details"]
    same = _review(client, tx, operator_headers, reason="Sem mudança", items=[
        {"item_id": a["id"], "food_id": foods["arroz_branco"], "proportion": 0.5},
        {"item_id": b["id"], "food_id": foods["sobremesa_do_dia"], "proportion": 0.5}])
    assert same.status_code == 422 and "Nenhuma alteração" in same.json()["error"]["message"]
    assert _review(client, tx, operator_headers, reason="Teste", items=[], ).status_code == 422
    assert client.post(f"/api/v1/transactions/{uuid.uuid4()}/review", json={"reason": "abc", "confirm": True}, headers=operator_headers).status_code == 404


def test_notes_only_change(client, foods, operator_headers):
    tx = _pending(client, foods)
    body = _review(client, tx, operator_headers, reason="Observação", notes="Cliente pediu sem sal").json()
    assert body["notes"] == "Cliente pediu sem sal" and body["status"] == "pending_review"


def test_replacing_with_inactive_food_is_flagged(client, foods, operator_headers, manager_headers):
    client.patch(f"/api/v1/foods/{foods['farofa']}", json={"active": False}, headers=manager_headers)
    tx = _pending(client, foods, items=[("arroz_branco", 0.5), ("sobremesa_do_dia", 0.5)])
    a, d = _item(tx, "arroz_branco"), _item(tx, "sobremesa_do_dia")
    body = _review(client, tx, operator_headers, reason="Trocar", items=[
        {"item_id": a["id"], "food_id": foods["arroz_branco"], "proportion": 0.5},
        {"item_id": d["id"], "food_id": foods["farofa"], "proportion": 0.5}]).json()
    assert "alimento_inativo" in body["review_reasons"] and "custo_indisponivel" not in body["review_reasons"]


# -------------------------------------------------------------------- histórico


def test_history_endpoints_require_manager(client, foods, operator_headers, manager_headers):
    tx = _pending(client, foods)
    _review(client, tx, operator_headers, reason="Observação", notes="n1")
    url = f"/api/v1/transactions/{tx['id']}/history"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=operator_headers).status_code == 403
    history = client.get(url, headers=manager_headers).json()
    assert [h["action"] for h in history] == ["create", "correction"]
    assert history[1]["operator_username"].startswith("operator_") and history[1]["reason"] == "Observação"
    assert history[1]["before"]["notes"] is None and history[1]["after"]["notes"] == "n1"
    assert client.get(f"/api/v1/transactions/{uuid.uuid4()}/history", headers=manager_headers).status_code == 404

    page = client.get("/api/v1/audit-logs", params={"entity_type": "transaction", "entity_id": tx["id"], "action": "correction"}, headers=manager_headers).json()
    assert page["total"] == 1
    assert client.get("/api/v1/audit-logs", headers=operator_headers).status_code == 403
