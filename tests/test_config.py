from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BASE_DIR, Settings
from app.core.enums import CameraMode, DatabaseMode, RecognitionMode, ScaleMode


def test_defaults_match_initial_configuration(monkeypatch):
    for var in ("SCALE_MODE", "CAMERA_MODE", "RECOGNITION_MODE", "DATABASE_MODE"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert settings.scale_mode is ScaleMode.MOCK
    assert settings.camera_mode is CameraMode.WEBCAM
    assert settings.recognition_mode is RecognitionMode.MOCK
    assert settings.database_mode is DatabaseMode.SQLITE


def test_values_come_from_environment(monkeypatch):
    monkeypatch.setenv("SCALE_MODE", "serial")
    monkeypatch.setenv("CAMERA_MODE", "upload")
    monkeypatch.setenv("RECOGNITION_MODE", "api")
    monkeypatch.setenv("MAX_UPLOAD_MB", "3")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://192.168.0.10:8000")
    settings = Settings(_env_file=None)
    assert settings.scale_mode is ScaleMode.SERIAL
    assert settings.camera_mode is CameraMode.UPLOAD
    assert settings.recognition_mode is RecognitionMode.API
    assert settings.max_upload_bytes == 3 * 1024 * 1024
    assert settings.cors_origins == ["http://localhost:3000", "http://192.168.0.10:8000"]


def test_invalid_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("SCALE_MODE", "raspberry")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("origins", ["*", "http://*.exemplo.com", "localhost:8000"])
def test_cors_rejects_wildcards_and_invalid_origins(origins):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=origins)


def test_relative_paths_are_resolved_from_project_root():
    settings = Settings(_env_file=None, sqlite_path=Path("data/x.db"))
    assert settings.sqlite_path == (BASE_DIR / "data" / "x.db").resolve()
    assert settings.sqlalchemy_url.get_backend_name() == "sqlite"
    assert settings.sqlalchemy_url.database == str(settings.sqlite_path)


def test_postgresql_url_hides_password():
    settings = Settings(_env_file=None, database_mode="postgresql", postgres_password="senha-super-secreta")
    url = settings.sqlalchemy_url
    assert url.drivername == "postgresql+psycopg"
    assert "senha-super-secreta" not in str(url)
    assert "senha-super-secreta" not in repr(settings)


def test_database_url_must_match_mode():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_mode="sqlite", database_url="postgresql+psycopg://u:p@h/db")


def test_env_example_documents_initial_modes():
    content = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    for line in ("SCALE_MODE=mock", "CAMERA_MODE=webcam", "RECOGNITION_MODE=mock", "DATABASE_MODE=sqlite"):
        assert line in content.splitlines()


def test_env_example_loads_completely(monkeypatch):
    """O .env.example precisa ser válido do jeito que está (valores lidos como texto)."""
    import os

    for key in list(os.environ):
        if key.startswith(("SCALE_", "CAMERA_", "RECOGNITION_", "DATABASE_", "DEFAULT_")):
            monkeypatch.delenv(key, raising=False)
    from app.services.scale.serial_scale import SerialScaleConfig

    settings = Settings(_env_file=BASE_DIR / ".env.example")
    assert settings.scale_serial_bytesize == 8
    assert settings.scale_serial_stopbits == 1
    assert settings.default_price_per_kg is not None
    config = SerialScaleConfig.from_settings(settings)
    assert config.line_terminator == b"\r\n"
    assert config.stopbits == 1 and isinstance(config.stopbits, int)


@pytest.mark.parametrize(("name", "value"), [("SCALE_SERIAL_BYTESIZE", "9"), ("SCALE_SERIAL_STOPBITS", "3")])
def test_invalid_serial_frame_settings(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
