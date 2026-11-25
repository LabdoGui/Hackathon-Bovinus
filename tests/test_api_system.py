from fastapi.testclient import TestClient


def test_health_reports_modes(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["modes"] == {"scale": "mock", "camera": "mock", "recognition": "mock", "database": "sqlite"}


def test_health_returns_503_when_database_is_down(app, client, monkeypatch):
    monkeypatch.setattr(app.state.db, "ping", lambda: False)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_request_id_and_security_headers(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"

    invalid = client.get("/api/v1/health", headers={"X-Request-ID": "<script>"})
    assert invalid.headers["X-Request-ID"] != "<script>"
    assert len(invalid.headers["X-Request-ID"]) == 32


def test_index_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PratoCusto AI" in response.text


def test_openapi_is_versioned(client):
    schema = client.get("/api/v1/openapi.json").json()
    paths = schema["paths"]
    for path in ("/api/v1/health", "/api/v1/foods", "/api/v1/recipes", "/api/v1/ingredients", "/api/v1/operators"):
        assert path in paths
    assert "APIKeyHeader" in schema["components"]["securitySchemes"]


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/nao-existe")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_body_larger_than_limit_is_rejected(client, admin_headers):
    payload = b"x" * (2 * 1024 * 1024)
    response = client.post(
        "/api/v1/foods", content=payload, headers={**admin_headers, "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_cors_allows_only_configured_origins(client):
    allowed = client.options(
        "/api/v1/foods",
        headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:8000"

    denied = client.options(
        "/api/v1/foods",
        headers={"Origin": "http://site-malicioso.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers


def test_unhandled_errors_return_generic_500(app):
    @app.get("/boom")
    def boom():
        raise RuntimeError("detalhe interno que não deve vazar")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "detalhe interno" not in response.text
