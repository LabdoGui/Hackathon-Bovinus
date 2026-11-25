import io
import json
import uuid
from decimal import Decimal

import httpx
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import Settings
from app.core.enums import AuditAction, MockScenario, RecognitionStatus
from app.database.seed import seed_demo_data
from app.models import AuditLog, Food, RecognitionResult, Transaction
from app.services.recognition import ApiFoodRecognitionService, LocalFoodRecognitionService, MockFoodRecognitionService

SECRET = "chave-super-secreta-123"


@pytest.fixture
def foods(app):
    with app.state.db.session_scope() as session:
        seed_demo_data(session)
        return {f.recognition_class: str(f.id) for f in session.scalars(select(Food))}


def _capture(client, seed=1) -> str:
    array = (np.random.default_rng(seed).random((720, 1280, 3)) * 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=70)
    response = client.post("/api/v1/camera/uploads", files={"file": ("p.jpg", buffer.getvalue(), "image/jpeg")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _reading(client, gross=650, tare=150) -> str:
    return client.post("/api/v1/scale/readings", json={"simulated_weight_g": gross, "tare_g": tare}).json()["id"]


def _use_scenario(app, scenario):
    app.state.recognition = MockFoodRecognitionService(scenario)


# --------------------------------------------------------------------- status


def test_status_declares_simulation(client):
    body = client.get("/api/v1/recognition/status").json()
    assert body["mode"] == "mock" and body["is_simulated"] is True
    assert body["model_available"] is False and "SIMULADO" in body["message"]
    assert body["details"]["scenario"] == "random"


def test_status_for_local_and_api_never_claims_a_model(app, client, settings):
    app.state.recognition = LocalFoodRecognitionService(None)
    body = client.get("/api/v1/recognition/status").json()
    assert body["mode"] == "local" and body["model_available"] is False and body["is_simulated"] is False
    assert "Nenhum modelo" in body["message"]

    api = ApiFoodRecognitionService(Settings(**{**settings.model_dump(), "recognition_api_url": "https://x.exemplo.com/a", "recognition_api_key": SECRET}))
    app.state.recognition = api
    body = client.get("/api/v1/recognition/status").json()
    assert body["details"] == {"provider": "api", "api_host": "x.exemplo.com", "api_key_configured": True}
    assert SECRET not in json.dumps(body)


# -------------------------------------------------------------------- analyze


def test_analyze_mock_returns_complete_detections(client, foods, db_session):
    capture = _capture(client)
    response = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture, "net_weight_g": 500})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider"] == "mock" and body["is_simulated"] is True
    assert "SIMULADO" in body["notice"] and body["model_version"] is None
    assert body["net_weight_g"] == 500.0 and body["processing_ms"] is not None
    detections = body["detections"]
    assert 2 <= len(detections) <= 4
    for d in detections:
        assert set(d) == {
            "name", "recognition_class", "confidence", "segmented_area_px", "segmented_area_ratio", "proportion",
            "estimated_weight_g", "source", "food_id", "matched", "review_reasons",
        }
        assert d["source"] == "mock" and d["matched"] is True and d["food_id"]
    assert round(sum(d["proportion"] for d in detections), 4) == 1.0
    assert round(sum(d["estimated_weight_g"] for d in detections), 1) == 500.0

    stored = db_session.get(RecognitionResult, uuid.UUID(body["id"]))
    assert stored.is_simulated and stored.net_weight_g == Decimal("500.0")
    assert client.get(f"/api/v1/recognition/results/{body['id']}").json() == body
    audit = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "recognition")).all()
    assert len(audit) == 1 and audit[0].after["is_simulated"] is True


def test_analyze_is_deterministic_per_image(client, foods):
    capture = _capture(client)
    a = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture}).json()
    b = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture}).json()
    assert a["id"] != b["id"] and a["detections"] == b["detections"]
    assert all(d["estimated_weight_g"] is None for d in a["detections"])


def test_analyze_uses_scale_reading_weight(client, foods):
    reading = _reading(client)
    body = client.post(
        "/api/v1/recognition/analyze", json={"image_capture_id": _capture(client), "scale_reading_id": reading}
    ).json()
    assert body["net_weight_g"] == 500.0


@pytest.mark.parametrize(
    ("scenario", "status", "reasons"),
    [
        (MockScenario.CONFIDENT, "success", []),
        (MockScenario.UNCERTAIN, "uncertain", ["confianca_baixa"]),
        (MockScenario.UNKNOWN_FOOD, "uncertain", ["alimento_desconhecido"]),
        (MockScenario.EMPTY, "uncertain", ["nenhum_alimento_reconhecido"]),
    ],
)
def test_analyze_scenarios_drive_human_review(app, client, foods, scenario, status, reasons):
    _use_scenario(app, scenario)
    body = client.post("/api/v1/recognition/analyze", json={"image_capture_id": _capture(client)}).json()
    assert body["status"] == status
    assert body["requires_review"] is bool(reasons)
    assert body["review_reasons"] == reasons


def test_analyze_flags_poor_image_quality(client, foods, db_session):
    row = np.linspace(60, 200, 1280).astype(np.uint8)
    blurred = np.broadcast_to(row[None, :, None], (720, 1280, 3)).copy()  # contraste ok, sem bordas: desfocada
    buffer = io.BytesIO()
    Image.fromarray(blurred).save(buffer, format="PNG")
    capture = client.post("/api/v1/camera/uploads", files={"file": ("a.png", buffer.getvalue(), "image/png")}).json()
    assert capture["is_blurry"] is True
    body = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture["id"]}).json()
    assert "imagem_com_baixa_qualidade" in body["review_reasons"] and body["requires_review"]


def test_analyze_validations(client, foods):
    assert client.post("/api/v1/recognition/analyze", json={"image_capture_id": str(uuid.uuid4())}).status_code == 404
    capture = _capture(client)
    both = client.post(
        "/api/v1/recognition/analyze",
        json={"image_capture_id": capture, "net_weight_g": 100, "scale_reading_id": str(uuid.uuid4())},
    )
    assert both.status_code == 422
    missing = client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture, "scale_reading_id": str(uuid.uuid4())})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "business_rule_violation"
    assert client.post("/api/v1/recognition/analyze", json={}).status_code == 422


def test_failure_returns_503_records_failed_result_and_audit(app, client, foods, db_session):
    _use_scenario(app, MockScenario.FAILURE)
    response = client.post("/api/v1/recognition/analyze", json={"image_capture_id": _capture(client)})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "recognition_unavailable"
    assert "POST /api/v1/transactions" in error["details"]["alternative"]
    failed = db_session.get(RecognitionResult, uuid.UUID(error["details"]["recognition_result_id"]))
    assert failed.status is RecognitionStatus.FAILED and failed.error and failed.detections == []
    assert db_session.scalars(select(AuditLog).where(AuditLog.action == AuditAction.HARDWARE_FAILURE)).all()
    view = client.get(f"/api/v1/recognition/results/{failed.id}").json()
    assert view["status"] == "failed" and "manualmente" in view["notice"]


def test_local_mode_gives_clear_503(app, client, foods):
    app.state.recognition = LocalFoodRecognitionService(None)
    response = client.post("/api/v1/recognition/analyze", json={"image_capture_id": _capture(client)})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "recognition_local_unavailable"


def test_api_mode_end_to_end_with_fake_server(app, client, foods, settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(
            200,
            json={
                "model": {"name": "modelo-externo", "version": "2.1"},
                "detections": [
                    {"recognition_class": "arroz_branco", "confidence": 0.94, "proportion": 0.7},
                    {"recognition_class": "feijao_carioca", "confidence": 0.9, "proportion": 0.3},
                ],
            },
        )

    custom = Settings(**{**settings.model_dump(), "recognition_api_url": "https://ia.exemplo.com/analisar", "recognition_api_key": SECRET})
    app.state.recognition = ApiFoodRecognitionService(custom, transport=httpx.MockTransport(handler))
    body = client.post("/api/v1/recognition/analyze", json={"image_capture_id": _capture(client), "net_weight_g": 400}).json()
    assert body["provider"] == "api" and body["is_simulated"] is False and body["notice"] is None
    assert (body["model_name"], body["model_version"]) == ("modelo-externo", "2.1")
    assert body["status"] == "success" and body["requires_review"] is False
    assert [d["estimated_weight_g"] for d in body["detections"]] == [280.0, 120.0]
    assert [d["source"] for d in body["detections"]] == ["api", "api"]
    assert SECRET not in json.dumps(body)


def test_list_results_filter_by_capture(client, foods):
    c1, c2 = _capture(client, 1), _capture(client, 2)
    for capture in (c1, c1, c2):
        client.post("/api/v1/recognition/analyze", json={"image_capture_id": capture})
    assert client.get("/api/v1/recognition/results").json()["total"] == 3
    assert client.get("/api/v1/recognition/results", params={"image_capture_id": c1}).json()["total"] == 2
    assert client.get(f"/api/v1/recognition/results/{uuid.uuid4()}").status_code == 404


# ------------------------------------------------- transação a partir do reconhecimento


def _flow(client, app, scenario=MockScenario.CONFIDENT, **tx_extra):
    _use_scenario(app, scenario)
    reading = _reading(client)
    result = client.post(
        "/api/v1/recognition/analyze", json={"image_capture_id": _capture(client), "scale_reading_id": reading}
    ).json()
    response = client.post(
        "/api/v1/transactions/from-recognition",
        json={"recognition_result_id": result["id"], "scale_reading_id": reading, **tx_extra},
    )
    return result, response


def test_full_flow_mock_goes_to_review_because_it_is_simulated(client, app, foods):
    result, response = _flow(client, app)
    assert response.status_code == 201, response.text
    tx = response.json()
    assert tx["status"] == "pending_review" and tx["requires_review"] is True
    assert tx["review_reasons"] == ["reconhecimento_simulado"]
    assert tx["recognition_result_id"] == result["id"] and tx["image_capture_id"] == result["image_capture_id"]
    assert tx["net_weight_g"] == 500.0 and tx["charged_amount"] == 29.95
    assert [i["source"] for i in tx["items"]] == ["recognition"] * len(result["detections"])
    assert [i["recognition_class"] for i in tx["items"]] == [d["recognition_class"] for d in result["detections"]]
    assert [i["weight_g"] for i in tx["items"]] == [d["estimated_weight_g"] for d in result["detections"]]
    assert all(i["confidence"] is not None and i["is_corrected"] is False for i in tx["items"])
    assert sum(i["weight_g"] for i in tx["items"]) == pytest.approx(500.0)
    assert tx["food_cost"] is not None  # todos os alimentos do mock têm ficha técnica (ou há revisão por custo)


def test_mock_review_can_be_disabled(client, app, foods, settings):
    settings.recognition_mock_requires_review = False
    _, response = _flow(client, app)
    tx = response.json()
    assert tx["status"] == "confirmed" and tx["review_reasons"] == []


def test_uncertain_recognition_review_reasons_propagate(client, app, foods, settings):
    settings.recognition_mock_requires_review = False
    _, response = _flow(client, app, scenario=MockScenario.UNCERTAIN)
    tx = response.json()
    assert tx["status"] == "pending_review" and tx["review_reasons"] == ["confianca_baixa"]


def test_unknown_food_item_is_kept_without_cost(client, app, foods, settings):
    settings.recognition_mock_requires_review = False
    _, response = _flow(client, app, scenario=MockScenario.UNKNOWN_FOOD)
    tx = response.json()
    unknown = next(i for i in tx["items"] if i["recognition_class"] == "item_nao_cadastrado")
    assert unknown["food_id"] is None and unknown["cost"] is None and unknown["food_name"].startswith("Item não cadastrado")
    assert tx["food_cost"] is None and tx["gross_margin"] is None
    assert set(tx["review_reasons"]) == {"alimento_desconhecido", "custo_indisponivel"}


def test_recognition_cannot_back_two_transactions(client, app, foods):
    result, first = _flow(client, app)
    assert first.status_code == 201
    other_reading = _reading(client)
    second = client.post(
        "/api/v1/transactions/from-recognition",
        json={"recognition_result_id": result["id"], "scale_reading_id": other_reading},
    )
    assert second.status_code == 409


def test_failed_and_empty_results_cannot_become_transactions(client, app, foods):
    _, empty = _flow(client, app, scenario=MockScenario.EMPTY)
    assert empty.status_code == 422 and "manualmente" in empty.json()["error"]["message"]

    _use_scenario(app, MockScenario.FAILURE)
    failure = client.post("/api/v1/recognition/analyze", json={"image_capture_id": _capture(client, 9)}).json()
    response = client.post(
        "/api/v1/transactions/from-recognition",
        json={"recognition_result_id": failure["error"]["details"]["recognition_result_id"], "scale_reading_id": _reading(client)},
    )
    assert response.status_code == 422


def test_from_recognition_unknown_ids_and_idempotency(client, app, foods, db_session):
    assert client.post(
        "/api/v1/transactions/from-recognition",
        json={"recognition_result_id": str(uuid.uuid4()), "scale_reading_id": _reading(client)},
    ).status_code == 422

    _use_scenario(app, MockScenario.CONFIDENT)
    reading = _reading(client)
    result = client.post("/api/v1/recognition/analyze", json={"image_capture_id": _capture(client), "scale_reading_id": reading}).json()
    payload = {"recognition_result_id": result["id"], "scale_reading_id": reading}
    headers = {"Idempotency-Key": "recog-000001"}
    first = client.post("/api/v1/transactions/from-recognition", json=payload, headers=headers)
    replay = client.post("/api/v1/transactions/from-recognition", json=payload, headers=headers)
    assert first.status_code == 201 and replay.status_code == 200 and first.json()["id"] == replay.json()["id"]
    assert len(db_session.scalars(select(Transaction)).all()) == 1
    other = client.post("/api/v1/transactions/from-recognition", json={**payload, "price_per_kg": 10}, headers=headers)
    assert other.status_code == 409


def test_price_override_and_notes(client, app, foods):
    _, response = _flow(client, app, price_per_kg=80, notes="Prato com salada extra")
    tx = response.json()
    assert tx["charged_amount"] == 40.0 and tx["notes"] == "Prato com salada extra"


def test_recognition_values_are_preserved_for_audit(client, app, foods, db_session):
    result, response = _flow(client, app)
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "transaction", AuditLog.entity_id == response.json()["id"])
    ).one()
    snapshot_items = audit.after["items"]
    assert {i["source"] for i in snapshot_items} == {"recognition"}
    assert [i["recognition_class"] for i in snapshot_items] == [d["recognition_class"] for d in result["detections"]]
    stored = db_session.get(RecognitionResult, uuid.UUID(result["id"]))
    assert stored.detections[0]["proportion"] == f"{result['detections'][0]['proportion']:.4f}"
