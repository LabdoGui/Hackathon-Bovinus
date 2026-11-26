import io

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.api.inventory import collect_routes, render_endpoints_markdown
from app.core.config import BASE_DIR, Settings
from app.core.enums import OperatorRole
from app.core.ratelimit import FailureLimiter
from app.models import AuditLog, Operator


# ------------------------------------------------------------------ Host (DNS rebinding)


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "[::1]:8000", ""])
def test_unknown_host_is_rejected_everywhere(client, host):
    for path in ("/api/v1/health", "/docs", "/dashboard"):
        response = client.get(path, headers={"Host": host})
        assert response.status_code == 400, (path, host)
        assert response.json()["error"]["code"] == "invalid_host"


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000", "LOCALHOST:9000", "testserver"])
def test_allowed_hosts_ignore_port_and_case(client, host):
    assert client.get("/api/v1/health", headers={"Host": host}).status_code == 200


def test_allowed_hosts_setting_validation():
    assert Settings(_env_file=None, allowed_hosts="Caixa1, 192.168.0.10").allowed_hosts == ["caixa1", "192.168.0.10"]
    for bad in ("*", "http://caixa", "caixa:8000", "a/b", ""):
        with pytest.raises(ValueError):
            Settings(_env_file=None, allowed_hosts=bad)


# ------------------------------------------------------- Origin (escrita entre sites)


def _png_bytes() -> bytes:
    array = (np.random.default_rng(1).random((720, 1280, 3)) * 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_cross_site_writes_are_blocked_even_without_preflight(client):
    evil = {"Origin": "https://site-malicioso.example"}
    # "requisição simples" sem corpo: dispara a câmera
    capture = client.post("/api/v1/camera/captures", headers=evil)
    # multipart: também não faz preflight
    upload = client.post("/api/v1/camera/uploads", headers=evil, files={"file": ("a.jpg", _png_bytes(), "image/jpeg")})
    reading = client.post("/api/v1/scale/readings", headers=evil, json={})
    for response in (capture, upload, reading):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_not_allowed"
    assert client.get("/api/v1/camera/captures").json()["total"] == 0  # nada foi gravado


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_other_unsafe_methods_are_checked_too(client, admin_headers, method):
    headers = {**admin_headers, "Origin": "https://site-malicioso.example"}
    assert getattr(client, method)("/api/v1/scale/tare", headers=headers).status_code == 403


def test_null_origin_is_blocked(client):
    assert client.post("/api/v1/camera/captures", headers={"Origin": "null"}).status_code == 403


def test_legitimate_origins_are_allowed(client):
    assert client.post("/api/v1/camera/captures", headers={"Origin": "http://localhost:8000"}).status_code == 201  # CORS_ORIGINS
    assert client.post("/api/v1/camera/captures", headers={"Origin": "http://testserver"}).status_code == 201  # mesma origem
    assert client.post("/api/v1/camera/captures").status_code == 201  # curl/scripts: sem Origin


def test_reads_with_foreign_origin_are_not_blocked_by_guard(client):
    # A leitura é protegida pelo CORS (o navegador não entrega a resposta ao site de fora).
    response = client.get("/api/v1/foods", headers={"Origin": "https://site-malicioso.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# --------------------------------------------------------------- força bruta de chaves


def test_failed_keys_are_rate_limited_and_block_even_valid_keys(client, admin_headers, settings):
    bad = {"X-API-Key": "pc_chave_errada_" + "x" * 30}
    for _ in range(settings.auth_max_failures):
        assert client.get("/api/v1/operators/me", headers=bad).status_code == 401
    blocked = client.get("/api/v1/operators/me", headers=bad)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "too_many_attempts"
    assert int(blocked.headers["retry-after"]) > 0
    assert client.get("/api/v1/operators/me", headers=admin_headers).status_code == 429  # chave certa também espera
    assert client.get("/api/v1/health").status_code == 200  # sem chave: não afetado


def test_success_resets_the_failure_counter(client, admin_headers, settings):
    bad = {"X-API-Key": "pc_errada_" + "y" * 30}
    for _ in range(settings.auth_max_failures - 1):
        client.get("/api/v1/operators/me", headers=bad)
    assert client.get("/api/v1/operators/me", headers=admin_headers).status_code == 200
    for _ in range(settings.auth_max_failures - 1):
        assert client.get("/api/v1/operators/me", headers=bad).status_code == 401  # contagem recomeçou


def test_limiter_unit_window_and_capacity():
    now = [0.0]
    limiter = FailureLimiter(3, 60, clock=lambda: now[0])
    for _ in range(3):
        limiter.record_failure("a")
    assert limiter.retry_after("a") > 0 and limiter.retry_after("b") == 0
    now[0] = 61
    assert limiter.retry_after("a") == 0  # janela expirou
    limiter.record_failure("a")
    limiter.reset("a")
    assert limiter.retry_after("a") == 0

    from app.core import ratelimit

    ratelimit.MAX_TRACKED = 5
    try:
        small = FailureLimiter(1, 60, clock=lambda: now[0])
        for index in range(20):
            small.record_failure(f"ip{index}")
        assert len(small._failures) <= 5  # memória limitada
    finally:
        ratelimit.MAX_TRACKED = 10_000


# ----------------------------------------------------------------- API_REQUIRE_KEY


def test_require_key_closes_reads_and_hardware_but_not_health(client, settings, operator_headers):
    settings.api_require_key = True
    assert client.get("/api/v1/health").status_code == 200
    for path in ("/api/v1/foods", "/api/v1/camera/preview", "/api/v1/camera/captures", "/api/v1/scale/status", "/api/v1/transactions"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=operator_headers).status_code == 200, path
    assert client.post("/api/v1/scale/readings", json={}).status_code == 401
    assert client.post("/api/v1/scale/readings", json={}, headers=operator_headers).status_code == 201


def test_pages_tell_the_scripts_whether_a_key_is_required(client, settings):
    assert 'data-require-key="false"' in client.get("/camera").text
    settings.api_require_key = True
    page = client.get("/camera")
    assert page.status_code == 200 and 'data-require-key="true"' in page.text
    assert "pc_" not in page.text  # a página nunca embute dados nem chaves


# ----------------------------------------------------------- gestão de operadores


def _operator_id(client, headers, username):
    items = client.get("/api/v1/operators", headers=headers, params={"limit": 200}).json()["items"]
    return next(o["id"] for o in items if o["username"] == username)


def test_admin_can_update_role_name_and_deactivate(client, admin_headers, make_api_key):
    caixa_key = make_api_key(OperatorRole.OPERATOR, username="caixa_x")
    operator_id = _operator_id(client, admin_headers, "caixa_x")
    url = f"/api/v1/operators/{operator_id}"
    promoted = client.patch(url, json={"role": "manager", "name": "Maria Silva"}, headers=admin_headers)
    assert promoted.status_code == 200 and promoted.json()["role"] == "manager" and promoted.json()["name"] == "Maria Silva"
    assert client.get("/api/v1/reports/summary", headers={"X-API-Key": caixa_key}).status_code == 200  # novo perfil vale já
    assert client.patch(url, json={"active": False}, headers=admin_headers).json()["active"] is False
    assert client.get("/api/v1/operators/me", headers={"X-API-Key": caixa_key}).status_code == 401
    assert client.patch(url, json={"role": None}, headers=admin_headers).status_code == 422


def test_operator_management_requires_admin(client, manager_headers, operator_headers, admin_headers, make_api_key):
    make_api_key(OperatorRole.OPERATOR, username="alvo")
    target = _operator_id(client, admin_headers, "alvo")
    for headers in (None, operator_headers, manager_headers):
        assert client.patch(f"/api/v1/operators/{target}", json={"active": False}, headers=headers).status_code in (401, 403)
        assert client.post(f"/api/v1/operators/{target}/rotate-key", headers=headers).status_code in (401, 403)


def test_last_active_admin_cannot_be_removed(client, app, make_api_key):
    key = make_api_key(OperatorRole.ADMIN, username="unico_admin")
    headers = {"X-API-Key": key}
    only = _operator_id(client, headers, "unico_admin")
    for body in ({"active": False}, {"role": "manager"}, {"role": "operator", "active": False}):
        response = client.patch(f"/api/v1/operators/{only}", json=body, headers=headers)
        assert response.status_code == 409 and response.json()["error"]["code"] == "last_admin_protected"
    make_api_key(OperatorRole.ADMIN, username="segundo_admin")
    assert client.patch(f"/api/v1/operators/{only}", json={"role": "manager"}, headers=headers).status_code == 200


def test_rotate_key_invalidates_old_and_never_logs_secret(client, admin_headers, make_api_key, db_session):
    old_key = make_api_key(OperatorRole.OPERATOR, username="rotacionar")
    target = _operator_id(client, admin_headers, "rotacionar")
    response = client.post(f"/api/v1/operators/{target}/rotate-key", headers=admin_headers)
    assert response.status_code == 200
    new_key = response.json()["api_key"]
    assert new_key != old_key and new_key.startswith("pc_")
    assert client.get("/api/v1/operators/me", headers={"X-API-Key": old_key}).status_code == 401
    assert client.get("/api/v1/operators/me", headers={"X-API-Key": new_key}).status_code == 200
    assert client.post("/api/v1/operators/00000000-0000-0000-0000-000000000000/rotate-key", headers=admin_headers).status_code == 404

    logs = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "operator", AuditLog.entity_id == target)).all()
    assert any(log.reason == "Chave de API rotacionada" for log in logs)
    dump = " ".join(str(log.before) + str(log.after) + str(log.reason) for log in logs)
    assert new_key not in dump and old_key not in dump and "api_key_hash" not in dump
    assert db_session.scalar(select(Operator).where(Operator.username == "rotacionar")).api_key_hash != old_key


# ------------------------------------------------------- inventário de rotas / docs

PUBLIC_WRITES = {
    "POST /api/v1/scale/readings",
    "POST /api/v1/camera/captures",
    "POST /api/v1/camera/uploads",
    "POST /api/v1/recognition/analyze",
    "POST /api/v1/transactions",
    "POST /api/v1/transactions/preview",
    "POST /api/v1/transactions/from-recognition",
}


def test_every_mutating_route_is_protected_except_the_documented_ones(app):
    routes = collect_routes(app)
    unsafe = [r for r in routes if r.method in {"POST", "PUT", "PATCH", "DELETE"}]
    open_ones = {f"{r.method} {r.path}" for r in unsafe if r.access == "public"}
    assert open_ones == PUBLIC_WRITES, "rota de escrita aberta sem estar na lista documentada"
    # só chamadas do fluxo de pesagem ficam abertas; cadastro, cancelamento, revisão e admin exigem perfil
    levels = {f"{r.method} {r.path}": r.access for r in unsafe}
    assert levels["POST /api/v1/transactions/{transaction_id}/review"] == "operator"
    assert levels["POST /api/v1/transactions/{transaction_id}/cancel"] == "manager"
    assert levels["PUT /api/v1/scale/tare"] == "manager"
    assert levels["POST /api/v1/admin/backups"] == "admin"
    assert levels["POST /api/v1/operators"] == "admin"
    assert levels["POST /api/v1/operators/{operator_id}/rotate-key"] == "admin"
    assert levels["DELETE /api/v1/foods/{food_id}"] == "manager"


def test_sensitive_reads_require_manager_or_admin(app):
    levels = {f"{r.method} {r.path}": r.access for r in collect_routes(app)}
    for key in ("GET /api/v1/audit-logs", "GET /api/v1/reports/summary", "GET /api/v1/reports/transactions.csv",
                "GET /api/v1/transactions/{transaction_id}/history"):
        assert levels[key] == "manager", key
    assert levels["GET /api/v1/operators"] == "admin" and levels["GET /api/v1/admin/backups"] == "admin"


def test_inventory_matches_openapi(app, client):
    schema = client.get("/api/v1/openapi.json").json()
    documented = {f"{m.upper()} {p}" for p, ops in schema["paths"].items() for m in ops if m != "parameters"}
    inventory = {f"{r.method} {r.path}" for r in collect_routes(app)}
    assert inventory == documented


def test_endpoints_doc_is_up_to_date(app):
    current = (BASE_DIR / "docs" / "endpoints.md").read_text(encoding="utf-8")
    assert current == render_endpoints_markdown(app), "docs/endpoints.md desatualizado: rode `python -m app.cli docs`"
