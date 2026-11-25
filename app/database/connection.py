"""Conexão com o banco de dados.

A camada de regras de negócio usa apenas ``Session`` do SQLAlchemy; trocar
SQLite por PostgreSQL é feito só pela configuração (``DATABASE_MODE``).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base

logger = logging.getLogger(__name__)


def _sqlite_on_connect(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


class Database:
    def __init__(self, url: URL | str, *, echo: bool = False) -> None:
        self.url = make_url(url)
        if self.is_sqlite:
            engine = create_engine(
                self.url,
                echo=echo,
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            event.listen(engine, "connect", _sqlite_on_connect)
        else:
            engine = create_engine(self.url, echo=echo, pool_pre_ping=True, pool_size=5, max_overflow=10)
        self.engine: Engine = engine
        self.session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @property
    def is_sqlite(self) -> bool:
        return self.url.get_backend_name() == "sqlite"

    @property
    def sqlite_file(self) -> Path | None:
        if not self.is_sqlite or not self.url.database or self.url.database == ":memory:":
            return None
        return Path(self.url.database)

    def prepare(self) -> None:
        """Cria o diretório do arquivo SQLite, se necessário."""
        if (path := self.sqlite_file) is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def session(self) -> Session:
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao conectar ao banco de dados")
            return False

    def create_all(self) -> None:
        """Somente para testes. Em uso normal, as tabelas vêm das migrações Alembic."""
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
