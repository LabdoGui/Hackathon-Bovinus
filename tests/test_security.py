import logging

from sqlalchemy import select

from app.core.enums import OperatorRole
from app.core.logging import RedactingFilter, redact
from app.core.security import generate_api_key, hash_api_key, role_satisfies
from app.models import Operator

FOOD = {"name": "Arroz", "recognition_class": "arroz"}


def test_api_key_generation_and_hash():
    key = generate_api_key()
    assert key.startswith("pc_") and len(key) > 40
    assert generate_api_key() != key
    assert hash_api_key(key) == hash_api_key(key)
    assert key not in hash_api_key(key)


def test_role_hierarchy():
    assert role_satisfies(OperatorRole.ADMIN, OperatorRole.MANAGER)
    assert role_satisfies(OperatorRole.MANAGER, OperatorRole.MANAGER)
    assert not role_satisfies(OperatorRole.OPERATOR, OperatorRole.MANAGER)


def test_admin_operation_requires_api_key(client):
    response = client.post("/api/v1/foods", json=FOOD)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "X-API-Key"


def test_invalid_api_key_is_rejected(client):
    response = client.post("/api/v1/foods", json=FOOD, headers={"X-API-Key": "pc_invalida"})
    assert response.status_code == 401


def test_operator_role_cannot_manage_catalog(client, operator_headers):
    response = client.post("/api/v1/foods", json=FOOD, headers=operator_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_manager_can_manage_catalog(client, manager_headers):
    assert client.post("/api/v1/foods", json=FOOD, headers=manager_headers).status_code == 201


def test_reads_do_not_require_key(client):
    assert client.get("/api/v1/foods").status_code == 200


def test_inactive_operator_is_rejected(client, app, make_api_key):
    key = make_api_key(OperatorRole.ADMIN, username="inativo")
    with app.state.db.session_scope() as session:
        session.scalar(select(Operator).where(Operator.username == "inativo")).active = False
    assert client.get("/api/v1/operators/me", headers={"X-API-Key": key}).status_code == 401


def test_admin_creates_operator_and_key_is_stored_hashed(client, admin_headers, db_session):
    response = client.post(
        "/api/v1/operators", json={"name": "Caixa 1", "username": "caixa1", "role": "operator"}, headers=admin_headers
    )
    assert response.status_code == 201
    api_key = response.json()["api_key"]

    me = client.get("/api/v1/operators/me", headers={"X-API-Key": api_key})
    assert me.status_code == 200
    assert me.json()["username"] == "caixa1"
    assert "api_key" not in me.json()

    stored = db_session.scalar(select(Operator).where(Operator.username == "caixa1"))
    assert stored.api_key_hash == hash_api_key(api_key)
    assert api_key not in repr(stored)


def test_only_admin_creates_operators(client, manager_headers):
    response = client.post(
        "/api/v1/operators", json={"name": "X", "username": "xyz", "role": "admin"}, headers=manager_headers
    )
    assert response.status_code == 403


def test_duplicate_username_conflict(client, admin_headers):
    body = {"name": "Caixa", "username": "caixa", "role": "operator"}
    assert client.post("/api/v1/operators", json=body, headers=admin_headers).status_code == 201
    assert client.post("/api/v1/operators", json=body, headers=admin_headers).status_code == 409


def test_redact_masks_sensitive_values():
    key = generate_api_key()
    text = redact(f"X-API-Key: {key} password=1234 url=postgresql://user:segredo@host/db token={key}")
    assert key not in text
    assert "1234" not in text
    assert "segredo" not in text


def test_redacting_filter_cleans_log_records():
    key = generate_api_key()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "chave recebida %s", (key,), None)
    RedactingFilter().filter(record)
    assert key not in record.getMessage()


def test_validation_errors_do_not_echo_input(client, manager_headers):
    response = client.post(
        "/api/v1/ingredients",
        json={"name": "Teste", "unit_cost": "valor-secreto-invalido"},
        headers=manager_headers,
    )
    assert response.status_code == 422
    assert "valor-secreto-invalido" not in response.text
