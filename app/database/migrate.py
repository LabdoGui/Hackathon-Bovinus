"""Execução programática das migrações Alembic."""

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from app.core.config import BASE_DIR


def alembic_config(url: URL | str | None = None) -> Config:
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "app" / "database" / "migrations"))
    config.attributes["configure_logger"] = False
    if url is not None:
        config.attributes["sqlalchemy_url"] = url
    return config


def upgrade_to_head(url: URL | str | None = None) -> None:
    command.upgrade(alembic_config(url), "head")
