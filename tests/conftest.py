"""Fixtures de teste. Nenhum teste depende de balança ou webcam física."""

import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import CameraMode, Environment, OperatorRole, RecognitionMode, ScaleMode
from app.main import create_app
from app.services.operators import OperatorService


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        app_env=Environment.TEST,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        log_to_file=False,
        sqlite_path=tmp_path / "data" / "test.db",
        db_auto_migrate=False,
        scale_mode=ScaleMode.MOCK,
        camera_mode=CameraMode.MOCK,
        recognition_mode=RecognitionMode.MOCK,
        max_upload_mb=1,
        scale_sample_interval_ms=0,
        scale_stabilization_timeout_s=2,
        default_price_per_kg=Decimal("59.90"),
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    application.state.db.prepare()
    application.state.db.create_all()
    yield application
    application.state.db.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(app: FastAPI) -> Iterator[Session]:
    session = app.state.db.session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_api_key(app: FastAPI) -> Callable[..., str]:
    def _make(role: OperatorRole = OperatorRole.ADMIN, username: str | None = None) -> str:
        with app.state.db.session_scope() as session:
            _, api_key = OperatorService(session).create(
                name=f"Teste {role.value}",
                username=username or f"{role.value}_{uuid.uuid4().hex[:8]}",
                role=role,
            )
        return api_key

    return _make


@pytest.fixture
def admin_headers(make_api_key) -> dict[str, str]:
    return {"X-API-Key": make_api_key(OperatorRole.ADMIN)}


@pytest.fixture
def manager_headers(make_api_key) -> dict[str, str]:
    return {"X-API-Key": make_api_key(OperatorRole.MANAGER)}


@pytest.fixture
def operator_headers(make_api_key) -> dict[str, str]:
    return {"X-API-Key": make_api_key(OperatorRole.OPERATOR)}
