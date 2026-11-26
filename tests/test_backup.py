import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, select

from app import cli
from app.core.enums import AuditAction
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.database.connection import Database
from app.database.migrate import alembic_config
from app.database.seed import seed_demo_data
from app.models import AuditLog, Food
from app.services.backup import BACKUP_PATTERN, BackupError, BackupScheduler, BackupService, known_revisions


@pytest.fixture
def service(app, settings) -> BackupService:
    # Num banco real as tabelas vêm das migrações (que registram a versão do esquema).
    command.stamp(alembic_config(app.state.db.url), "head")
    return BackupService(app.state.db, settings)


def _count_foods(path: Path) -> int:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute("SELECT count(*) FROM foods").fetchone()[0]
    finally:
        connection.close()


def _seed(app):
    with app.state.db.session_scope() as session:
        seed_demo_data(session)


# --------------------------------------------------------------------- criação


def test_backup_is_consistent_verified_and_named(app, service, settings):
    _seed(app)  # gravado pelo WAL: o backup precisa incluir mesmo sem checkpoint
    info = service.create()
    path = settings.backup_dir / info.filename
    assert BACKUP_PATTERN.match(info.filename) and path.is_file()
    assert info.integrity == "ok" and len(info.sha256) == 64 and info.size_bytes == path.stat().st_size
    assert info.schema_revision in known_revisions()
    assert _count_foods(path) == 9
    assert not list(settings.backup_dir.glob("*.tmp"))


def test_backup_is_a_single_self_contained_file(app, service, settings):
    """Regressão: a cópia herdava o modo WAL e deixava arquivos -wal/-shm órfãos ao lado do backup."""
    _seed(app)
    assert app.state.db.engine.connect().exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    first = service.create()
    second = service.create()
    assert sorted(p.name for p in settings.backup_dir.iterdir()) == sorted([first.filename, second.filename])
    connection = sqlite3.connect(f"{(settings.backup_dir / first.filename).as_uri()}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()
    assert sorted(p.name for p in settings.backup_dir.iterdir()) == sorted([first.filename, second.filename])  # abrir não cria nada


def test_stale_temporary_files_are_cleaned_but_unrelated_files_are_kept(service, settings):
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    leftovers = ["pratocusto-20200101-000000.tmp", "pratocusto-20200101-000000.tmp-wal", "pratocusto-20200101-000000.tmp-shm"]
    keep = ["meu-arquivo.tmp", "pratocusto.tmp", "anotacoes.txt"]
    for name in leftovers + keep:
        (settings.backup_dir / name).write_text("x")
    service.create()
    remaining = {p.name for p in settings.backup_dir.iterdir()}
    assert not set(leftovers) & remaining and set(keep) <= remaining


def test_restore_leaves_no_sidecar_files_and_safety_copy_is_single_file(app, service, settings):
    _seed(app)
    info = service.create()
    app.state.db.dispose()
    live, safety = service.restore(settings.backup_dir / info.filename)
    assert {p.name for p in settings.backup_dir.iterdir()} == {info.filename, safety.name}
    assert not list(live.parent.glob("*.restore-tmp*"))


def test_backup_does_not_block_or_corrupt_concurrent_writes(app, service, settings):
    _seed(app)
    first = service.create()
    with app.state.db.session_scope() as session:
        session.add(Food(name="Novo", recognition_class="novo"))
    second = service.create()
    assert _count_foods(settings.backup_dir / first.filename) == 9
    assert _count_foods(settings.backup_dir / second.filename) == 10


def test_same_second_backups_do_not_overwrite(service, settings):
    moment = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    names = {service.create(now=moment).filename for _ in range(3)}
    assert names == {"pratocusto-20260101-120000.db", "pratocusto-20260101-120000-1.db", "pratocusto-20260101-120000-2.db"}


def test_retention_keeps_newest_and_never_touches_other_files(app, settings):
    settings.backup_keep = 3
    service = BackupService(app.state.db, settings)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    (settings.backup_dir / "anotacoes.txt").write_text("não apague")
    (settings.backup_dir / "pre-restore-20200101-000000.db").write_text("segurança")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for day in range(5):
        service.create(now=base + timedelta(days=day))
    kept = sorted(p.name for p in settings.backup_dir.glob("pratocusto-*.db"))
    assert kept == ["pratocusto-20260103-000000.db", "pratocusto-20260104-000000.db", "pratocusto-20260105-000000.db"]
    assert (settings.backup_dir / "anotacoes.txt").exists() and (settings.backup_dir / "pre-restore-20200101-000000.db").exists()
    assert [b.filename for b in service.list()] == kept[::-1]  # mais recente primeiro


def test_postgresql_is_reported_as_unsupported(settings):
    class FakeDatabase:
        sqlite_file = None

    with pytest.raises(BusinessRuleError) as error:
        BackupService(FakeDatabase(), settings).create()
    assert error.value.code == "backup_not_supported" and "pg_dump" in error.value.message


def test_backup_before_database_exists_fails_clearly(tmp_path, settings):
    database = Database(f"sqlite:///{tmp_path / 'nao_existe.db'}")
    with pytest.raises(BackupError):
        BackupService(database, settings).create()


# ------------------------------------------------------------------- endpoints


def test_backup_endpoints_are_admin_only_and_audited(client, app, manager_headers, admin_headers, db_session):
    command.stamp(alembic_config(app.state.db.url), "head")
    _seed(app)
    assert client.post("/api/v1/admin/backups").status_code == 401
    assert client.post("/api/v1/admin/backups", headers=manager_headers).status_code == 403
    assert client.get("/api/v1/admin/backups", headers=manager_headers).status_code == 403
    created = client.post("/api/v1/admin/backups", headers=admin_headers)
    assert created.status_code == 201
    body = created.json()
    assert body["integrity"] == "ok" and body["sha256"] and body["filename"].endswith(".db")
    listing = client.get("/api/v1/admin/backups", headers=admin_headers).json()
    assert [b["filename"] for b in listing] == [body["filename"]] and listing[0]["sha256"] is None
    audit = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "backup")).one()
    assert audit.action is AuditAction.CREATE and audit.entity_id == body["filename"] and audit.operator_id is not None


# ------------------------------------------------------------------ restauração


def test_restore_roundtrip_keeps_safety_copy(app, service, settings):
    _seed(app)
    info = service.create()
    with app.state.db.session_scope() as session:
        for food in session.scalars(select(Food)):
            session.delete(food)
    assert _count_foods(settings.sqlite_path) == 0
    app.state.db.dispose()  # a aplicação precisa estar parada

    live, safety = service.restore(settings.backup_dir / info.filename)
    assert _count_foods(live) == 9
    assert safety is not None and safety.name.startswith("pre-restore-") and _count_foods(safety) == 0
    assert not Path(str(live) + "-wal").exists() and not Path(str(live) + "-shm").exists()
    reopened = Database(app.state.db.url)
    try:
        with reopened.session_scope() as session:
            assert session.scalar(select(func.count()).select_from(Food)) == 9
    finally:
        reopened.dispose()


def test_restore_rejects_missing_corrupted_and_incompatible_files(service, settings, tmp_path):
    with pytest.raises(NotFoundError):
        service.restore(tmp_path / "nao_existe.db")

    garbage = tmp_path / "lixo.db"
    garbage.write_bytes(b"isto nao e um banco sqlite" * 50)
    with pytest.raises(BackupError):
        service.restore(garbage)

    future = tmp_path / "futuro.db"
    connection = sqlite3.connect(str(future))
    connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32))")
    connection.execute("INSERT INTO alembic_version VALUES ('9999_do_futuro')")
    connection.commit()
    connection.close()
    with pytest.raises(BackupError) as error:
        service.restore(future)
    assert "esquema desconhecida" in error.value.message

    no_version = tmp_path / "sem_versao.db"
    sqlite3.connect(str(no_version)).close()
    with pytest.raises(BackupError):
        service.restore(no_version)


# -------------------------------------------------------------------- agendador


def test_scheduler_runs_periodically_survives_errors_and_stops():
    calls = []

    def job():
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise RuntimeError("falha simulada")

    scheduler = BackupScheduler(job, 0.05)
    scheduler.start()
    deadline = time.monotonic() + 3
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    scheduler.stop()
    count = len(calls)
    assert count >= 3  # continuou depois da exceção
    time.sleep(0.2)
    assert len(calls) == count  # parou de fato


def test_scheduler_disabled_when_interval_is_zero():
    scheduler = BackupScheduler(lambda: pytest.fail("não deveria rodar"), 0)
    scheduler.start()
    assert scheduler._thread is None
    scheduler.stop()


def test_app_starts_scheduler_only_when_configured(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.backup_interval_hours = 1
    application = create_app(settings)
    application.state.db.prepare()
    application.state.db.create_all()
    with TestClient(application):
        assert application.state.backup_scheduler is not None and application.state.backup_scheduler._thread.is_alive()
    assert application.state.backup_scheduler._thread is None  # encerrado no shutdown


# ------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_env(app, settings, monkeypatch):
    command.stamp(alembic_config(app.state.db.url), "head")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "setup_logging", lambda s: None)
    monkeypatch.setattr(cli, "upgrade_to_head", lambda url: None)
    return settings


def test_cli_backup_and_restore(app, cli_env, capsys):
    _seed(app)
    assert cli.main(["backup"]) == 0
    out = capsys.readouterr().out
    assert "Backup criado" in out and "SHA-256" in out and "imagens" in out
    backup = next(cli_env.backup_dir.glob("pratocusto-*.db"))

    assert cli.main(["restore", str(backup)]) == 2  # exige --yes
    assert "--yes" in capsys.readouterr().err
    app.state.db.dispose()
    assert cli.main(["restore", str(backup), "--yes"]) == 0
    assert "Cópia do banco anterior" in capsys.readouterr().out
    assert cli.main(["restore", str(backup.parent / "nao_existe.db"), "--yes"]) == 1


def test_cli_operator_commands(app, cli_env, capsys):
    assert cli.main(["create-operator", "--name", "Ana", "--username", "ana", "--role", "admin"]) == 0
    first_key = capsys.readouterr().out.strip().splitlines()[-1]
    assert cli.main(["list-operators"]) == 0
    assert "ana" in capsys.readouterr().out
    assert cli.main(["rotate-key", "--username", "ana"]) == 0
    new_key = capsys.readouterr().out.strip().splitlines()[-1]
    assert new_key.startswith("pc_") and new_key != first_key
    assert cli.main(["rotate-key", "--username", "inexistente"]) == 1
    assert "não existe" in capsys.readouterr().err


def test_cli_docs_command_writes_endpoints(cli_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)
    (tmp_path / "docs").mkdir()
    assert cli.main(["docs"]) == 0
    assert "/api/v1/health" in (tmp_path / "docs" / "endpoints.md").read_text(encoding="utf-8")
