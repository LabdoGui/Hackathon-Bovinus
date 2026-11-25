from decimal import Decimal

import serial
from sqlalchemy import select

from app.core.enums import AuditAction, OperatorRole, ScaleMode
from app.models import AuditLog, ScaleReading
from app.services.scale import ScaleManager


def test_status(client):
    body = client.get("/api/v1/scale/status").json()
    assert body["configured_mode"] == "mock"
    assert body["available_sources"] == ["mock", "manual"]
    assert body["min_weight_g"] == 10.0
    assert body["device"]["device"] == "simulador"


def test_ports_endpoint_does_not_require_hardware(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.scale.list_serial_ports", lambda: [{"device": "COM3", "description": "USB-Serial", "hwid": "x"}]
    )
    assert client.get("/api/v1/scale/ports").json() == [{"device": "COM3", "description": "USB-Serial", "hwid": "x"}]


def test_mock_reading_is_stable_and_persisted(client, db_session):
    response = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 650, "tare_g": 150})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "mock"
    assert body["stable"] is True
    assert (body["gross_weight_g"], body["tare_g"], body["net_weight_g"]) == (650.0, 150.0, 500.0)
    assert body["valid_for_transaction"] is True and body["issues"] == []

    stored = db_session.get(ScaleReading, __import__("uuid").UUID(body["id"]))
    assert stored.net_weight_g == Decimal("500.0")
    assert client.get(f"/api/v1/scale/readings/{body['id']}").json()["id"] == body["id"]
    assert client.get("/api/v1/scale/readings").json()["total"] == 1


def test_reading_below_minimum_is_flagged(client):
    body = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 5}).json()
    assert body["valid_for_transaction"] is False
    assert "mínimo" in body["issues"][0]


def test_tare_greater_than_gross_is_flagged(client):
    body = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 100, "tare_g": 200}).json()
    assert body["net_weight_g"] == -100.0
    assert body["valid_for_transaction"] is False


def test_manual_reading(client):
    missing = client.post("/api/v1/scale/readings", json={"source": "manual"})
    assert missing.status_code == 422
    body = client.post("/api/v1/scale/readings", json={"source": "manual", "manual_weight_g": 432.5}).json()
    assert body["mode"] == "manual" and body["gross_weight_g"] == 432.5


def test_source_not_enabled(client):
    response = client.post("/api/v1/scale/readings", json={"source": "serial"})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["available_sources"] == ["mock", "manual"]


def test_default_tare_requires_manager_and_is_applied(client, operator_headers, manager_headers):
    assert client.put("/api/v1/scale/tare", json={"tare_g": 120}).status_code == 401
    assert client.put("/api/v1/scale/tare", json={"tare_g": 120}, headers=operator_headers).status_code == 403
    assert client.put("/api/v1/scale/tare", json={"tare_g": 120}, headers=manager_headers).json() == {"tare_g": 120.0}
    assert client.get("/api/v1/scale/tare").json() == {"tare_g": 120.0}
    body = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 620}).json()
    assert body["tare_g"] == 120.0 and body["net_weight_g"] == 500.0


def test_negative_tare_rejected(client, manager_headers):
    assert client.put("/api/v1/scale/tare", json={"tare_g": -5}, headers=manager_headers).status_code == 422


def test_serial_failure_returns_503_logs_and_keeps_mock(app, settings, client, db_session):
    def failing_factory(**_):
        raise serial.SerialException("could not open port 'COM3'")

    settings.scale_mode = ScaleMode.SERIAL
    app.state.scale = ScaleManager(settings, serial_factory=failing_factory)

    response = client.post("/api/v1/scale/readings", json={})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "scale_unavailable"
    assert "COM3" in error["message"]
    assert error["details"]["fallback_sources"] == ["mock", "manual"]

    failed = db_session.get(ScaleReading, __import__("uuid").UUID(error["details"]["scale_reading_id"]))
    assert failed.error and failed.gross_weight_g is None and failed.mode.value == "serial"
    audit = db_session.scalars(select(AuditLog).where(AuditLog.action == AuditAction.HARDWARE_FAILURE)).all()
    assert len(audit) == 1 and audit[0].entity_type == "hardware"

    fallback = client.post("/api/v1/scale/readings", json={"source": "mock", "simulated_weight_g": 300})
    assert fallback.status_code == 201 and fallback.json()["mode"] == "mock"

    assert client.get("/api/v1/scale/status").json()["last_error"] is not None
    failed_view = client.get(f"/api/v1/scale/readings/{failed.id}").json()
    assert failed_view["valid_for_transaction"] is False


def test_reading_records_operator_when_key_is_sent(client, make_api_key, db_session):
    key = make_api_key(OperatorRole.OPERATOR, username="caixa")
    body = client.post("/api/v1/scale/readings", json={}, headers={"X-API-Key": key}).json()
    assert db_session.get(ScaleReading, __import__("uuid").UUID(body["id"])).operator_id is not None
