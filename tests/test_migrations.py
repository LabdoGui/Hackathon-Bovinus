from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.database.migrate import alembic_config, upgrade_to_head
from app.models import Base


def test_migrations_create_schema_identical_to_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    upgrade_to_head(url)

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables) <= tables
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_downgrade_removes_tables(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'down.db'}"
    upgrade_to_head(url)
    command.downgrade(alembic_config(url), "base")
    engine = create_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()


def test_application_auto_migrates_on_startup(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.db_auto_migrate = True
    settings.sqlite_path = tmp_path / "auto" / "auto.db"
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["database"] == "ok"
        assert client.get("/api/v1/foods").status_code == 200
    assert settings.sqlite_path.exists()
