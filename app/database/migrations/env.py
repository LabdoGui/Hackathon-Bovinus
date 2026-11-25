"""Ambiente de migrações Alembic do PratoCusto AI."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Base
from app.models.base import UTCDateTime

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url():
    return config.attributes.get("sqlalchemy_url") or get_settings().sqlalchemy_url


def _render_item(type_, obj, autogen_context):
    """Renderiza tipos próprios como tipos SQLAlchemy puros, para que as
    migrações não dependam do código da aplicação."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_item=_render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    url = _url()
    is_sqlite = str(url).startswith("sqlite")
    _configure(
        url=url.render_as_string(hide_password=False) if hasattr(url, "render_as_string") else url,
        literal_binds=True,
        render_as_batch=is_sqlite,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection) -> None:
    _configure(connection=connection, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
        return
    engine = create_engine(_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _run_with_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
