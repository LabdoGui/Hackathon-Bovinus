"""Concorrência, falhas de infraestrutura e inicialização."""

import io
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.enums import ScaleMode
from app.core.exceptions import ConflictError
from app.core.logging import setup_logging
from app.database.connection import Database
from app.database.migrate import alembic_config
from app.database.seed import seed_demo_data
from app.models import Food, ScaleReading, Transaction
from app.schemas.transaction import TransactionCreate, TransactionItemIn
from app.services.scale import ScaleManager
from app.services.scale_readings import ScaleReadingService
from app.services.scale.serial_scale import list_serial_ports
from app.services.transactions import TransactionService


@pytest.fixture
def prepared(app, settings):
    """Banco com seed, uma leitura válida e o payload de uma transação."""
    settings.default_price_per_kg = Decimal("59.90")
    with app.state.db.session_scope() as session:
        seed_demo_data(session)
        food_id = session.scalar(select(Food.id).where(Food.recognition_class == "arroz_branco"))
        reading = ScaleReading(
            mode=ScaleMode.MOCK, gross_weight_g=Decimal("650"), tare_g=Decimal("150"), net_weight_g=Decimal("500"), stable=True
        )
        session.add(reading)
        session.flush()
        reading_id = reading.id
    data = TransactionCreate(scale_reading_id=reading_id, items=[TransactionItemIn(food_id=food_id, proportion=Decimal("1"))])
    return app, settings, data


def _create(app, settings, data, key):
    """Uma "requisição": sessão própria, como no uso real."""
    session = app.state.db.session()
    try:
        service = TransactionService(session, settings, ScaleReadingService(session, ScaleManager(settings)))
        transaction, created = service.create(data, idempotency_key=key, operator=None)
        return ("created" if created else "replay", transaction.id)
    except ConflictError:
        return ("conflict", None)
    finally:
        session.close()


def _race(app, settings, data, key, workers=8):
    barrier = threading.Barrier(workers)

    def attempt(_):
        barrier.wait()
        return _create(app, settings, data, key)

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(attempt, range(workers)))


def _transactions(app) -> int:
    with app.state.db.session_scope() as session:
        return session.scalar(select(func.count()).select_from(Transaction))


def test_concurrent_requests_with_same_idempotency_key_create_one_transaction(prepared):
    app, settings, data = prepared
    results = _race(app, settings, data, "corrida-chave-0001")
    assert [r[0] for r in results].count("created") == 1
    assert {r[0] for r in results} <= {"created", "replay", "conflict"}
    assert _transactions(app) == 1
    ids = {r[1] for r in results if r[1] is not None}
    assert len(ids) == 1  # quem recebeu resposta recebeu a MESMA transação


def test_concurrent_requests_without_key_cannot_reuse_the_same_reading(prepared):
    app, settings, data = prepared
    results = _race(app, settings, data, None)
    assert [r[0] for r in results].count("created") == 1
    assert [r[0] for r in results].count("conflict") == len(results) - 1
    assert _transactions(app) == 1


# --------------------------------------------------------------- infraestrutura


def test_ping_reports_false_when_database_is_unreachable(tmp_path):
    broken = Database(f"sqlite:///{tmp_path}/pasta_que_nao_existe/banco.db")
    assert broken.ping() is False
    broken.dispose()


def test_session_scope_rolls_back_on_error(app):
    with pytest.raises(RuntimeError):
        with app.state.db.session_scope() as session:
            session.add(Food(name="Fantasma", recognition_class="fantasma"))
            session.flush()
            raise RuntimeError("falha no meio")
    with app.state.db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Food)) == 0


def test_list_serial_ports_works_without_hardware():
    ports = list_serial_ports()
    assert isinstance(ports, list)
    assert all({"device", "description", "hwid"} <= set(p) for p in ports)


def test_offline_migration_sql_for_postgresql(monkeypatch):
    """Gera o SQL das migrações para PostgreSQL sem precisar de um servidor.

    (Para SQLite o Alembic não gera SQL offline em modo batch; as migrações de SQLite são
    exercitadas ao vivo pelos demais testes.)
    """
    from app.core import config

    monkeypatch.setenv("DATABASE_MODE", "postgresql")
    config.get_settings.cache_clear()
    try:
        cfg = alembic_config()
        buffer = io.StringIO()
        cfg.output_buffer = buffer
        command.upgrade(cfg, "head", sql=True)
    finally:
        config.get_settings.cache_clear()
    sql = buffer.getvalue()
    for expected in ("CREATE TABLE transactions", "CREATE TABLE audit_logs", "JSONB", "TIMESTAMP WITH TIME ZONE"):
        assert expected in sql, expected


def test_file_logging_masks_secrets(tmp_path):
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        settings = Settings(_env_file=None, log_dir=tmp_path / "logs", log_to_file=True, log_level="INFO")
        setup_logging(settings)
        logging.getLogger("teste").info("chave recebida X-API-Key: pc_%s e password=segredo123", "a" * 32)
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = (tmp_path / "logs" / "pratocusto.log").read_text(encoding="utf-8")
        assert "chave recebida" in content
        assert "pc_" + "a" * 32 not in content
        assert "segredo123" not in content
        assert "X-API-Key: ***" in content and "password=***" in content
    finally:
        for handler in list(root.handlers):
            if handler not in saved_handlers:
                handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_module_entrypoint_starts_uvicorn_with_configured_host_and_port(monkeypatch):
    import app.__main__ as entry

    captured = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda target, **kwargs: captured.update(target=target, **kwargs))
    monkeypatch.setattr(entry, "get_settings", lambda: Settings(_env_file=None, host="127.0.0.1", port=8123))
    entry.main()
    assert captured["target"] == "app.main:app" and captured["host"] == "127.0.0.1" and captured["port"] == 8123
    assert captured["reload"] is False and captured["log_config"] is None


def test_opencv_grabber_reports_missing_device_and_backends():
    from app.services.camera.devices import BACKENDS, DeviceOpenError, OpenCVGrabber, default_backend_name

    assert set(BACKENDS) == {"auto", "dshow", "msmf", "v4l2"}
    assert default_backend_name("dshow") == "dshow" and default_backend_name("auto").startswith("auto (")
    with pytest.raises(DeviceOpenError):
        OpenCVGrabber(63, 640, 480)  # nenhuma câmera nesse índice
