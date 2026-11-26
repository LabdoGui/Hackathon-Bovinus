"""Backup e restauração do banco SQLite.

* Usa a API de backup online do SQLite: gera uma cópia **consistente** mesmo com a aplicação
  em uso (inclusive no modo WAL), ao contrário de copiar o arquivo `.db`.
* A cópia é gravada em arquivo temporário, verificada (``PRAGMA integrity_check`` e tabela de
  versão das migrações) e só então renomeada: um backup nunca aparece pela metade.
* Retenção: mantém os ``BACKUP_KEEP`` mais recentes (só apaga arquivos com o nome padrão).
* PostgreSQL não é coberto: use ``pg_dump`` (veja docs/backup.md).
* As imagens capturadas (``data/images``) NÃO fazem parte do backup do banco; copie essa pasta
  separadamente.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.script import ScriptDirectory

from app.core.config import Settings
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.database.connection import Database
from app.database.migrate import alembic_config

logger = logging.getLogger(__name__)

BACKUP_PATTERN = re.compile(r"^pratocusto-\d{8}-\d{6}(?:-\d+)?\.db$")
# Restos de uma execução interrompida (arquivo temporário e auxiliares do SQLite)
STALE_PATTERN = re.compile(r"^pratocusto-\d{8}-\d{6}(?:-\d+)?\.tmp(?:-wal|-shm|-journal)?$")


@dataclass(frozen=True)
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime
    sha256: str | None = None
    integrity: str | None = None
    schema_revision: str | None = None


class BackupError(BusinessRuleError):
    code = "backup_failed"


def _verify(path: Path) -> tuple[str, str | None]:
    """Confere integridade e devolve ``(resultado, revisão do esquema)``."""
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"Não foi possível abrir o arquivo de backup: {exc}") from exc
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.Error:
            row = None
        return result, row[0] if row else None
    except sqlite3.Error as exc:
        raise BackupError(f"Arquivo de backup inválido ou corrompido: {exc}") from exc
    finally:
        connection.close()


def _copy_database(source: sqlite3.Connection, destination: Path) -> None:
    """Copia o banco com a API de backup e deixa o destino em arquivo ÚNICO.

    O banco de origem usa o modo WAL e a cópia herdaria esse modo, o que faria cada abertura
    criar arquivos ``-wal``/``-shm`` ao lado do backup (e o backup só estaria completo junto
    com eles). Convertemos para ``journal_mode=DELETE``: um backup é um único arquivo.
    """
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
        target.commit()
    finally:
        target.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def known_revisions() -> set[str]:
    script = ScriptDirectory.from_config(alembic_config())
    return {rev.revision for rev in script.walk_revisions()}


class BackupService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.directory = settings.backup_dir

    # --------------------------------------------------------------- backup
    def _require_sqlite(self) -> Path:
        source = self.database.sqlite_file
        if source is None:
            raise BusinessRuleError(
                "Backup automático só existe para SQLite. Com PostgreSQL use pg_dump (docs/backup.md).",
                code="backup_not_supported",
            )
        return source

    def create(self, *, now: datetime | None = None) -> BackupInfo:
        source = self._require_sqlite()
        if not source.exists():
            raise BackupError("Banco de dados ainda não existe; nada a copiar.")
        self.directory.mkdir(parents=True, exist_ok=True)
        now = now or datetime.now(UTC)
        stem = f"pratocusto-{now:%Y%m%d-%H%M%S}"
        target = self.directory / f"{stem}.db"
        suffix = 1
        while target.exists():
            target = self.directory / f"{stem}-{suffix}.db"
            suffix += 1
        self._remove_stale()
        temporary = target.with_suffix(".tmp")
        try:
            src = sqlite3.connect(str(source), timeout=30)
            try:
                _copy_database(src, temporary)
            finally:
                src.close()
            integrity, revision = _verify(temporary)
            if integrity != "ok":
                raise BackupError(f"Verificação de integridade do backup falhou: {integrity}")
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        self.prune()
        info = BackupInfo(
            filename=target.name,
            size_bytes=target.stat().st_size,
            created_at=now,
            sha256=_sha256(target),
            integrity=integrity,
            schema_revision=revision,
        )
        logger.info("Backup criado: %s (%s bytes)", info.filename, info.size_bytes)
        return info

    def _remove_stale(self) -> None:
        """Apaga restos de backups interrompidos (somente arquivos com o nome temporário padrão)."""
        if self.directory.is_dir():
            for path in self.directory.iterdir():
                if path.is_file() and STALE_PATTERN.match(path.name):
                    path.unlink(missing_ok=True)

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(
            (p for p in self.directory.iterdir() if p.is_file() and BACKUP_PATTERN.match(p.name)),
            key=lambda p: p.name,
            reverse=True,
        )

    def list(self) -> list[BackupInfo]:
        return [
            BackupInfo(p.name, p.stat().st_size, datetime.fromtimestamp(p.stat().st_mtime, UTC)) for p in self._files()
        ]

    def prune(self) -> list[str]:
        removed = []
        for path in self._files()[self.settings.backup_keep :]:
            path.unlink(missing_ok=True)
            removed.append(path.name)
        if removed:
            logger.info("Backups antigos removidos: %s", ", ".join(removed))
        return removed

    # ------------------------------------------------------------ restauração
    def restore(self, backup_file: Path) -> tuple[Path, Path | None]:
        """Restaura ``backup_file`` sobre o banco atual. A APLICAÇÃO DEVE ESTAR PARADA.

        Antes de substituir, o banco atual é preservado em ``pre-restore-*.db``. O backup precisa
        passar na verificação de integridade e não pode ser de um esquema mais novo que o código.
        Retorna ``(banco restaurado, cópia de segurança do banco anterior)``.
        """
        live = self._require_sqlite()
        if not backup_file.is_file():
            raise NotFoundError(f"Arquivo de backup não encontrado: {backup_file}")
        integrity, revision = _verify(backup_file)
        if integrity != "ok":
            raise BackupError(f"O backup não passou na verificação de integridade: {integrity}")
        if revision is None or revision not in known_revisions():
            raise BackupError(
                f"O backup tem versão de esquema desconhecida ({revision!r}); provavelmente é de uma versão "
                "mais nova do sistema. Atualize o código antes de restaurar."
            )

        live.parent.mkdir(parents=True, exist_ok=True)
        safety: Path | None = None
        if live.exists():
            safety = self.directory / f"pre-restore-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
            self.directory.mkdir(parents=True, exist_ok=True)
            src = sqlite3.connect(str(live), timeout=30)
            try:
                _copy_database(src, safety)
            finally:
                src.close()

        staged = live.with_suffix(".restore-tmp")
        staged.unlink(missing_ok=True)
        src = sqlite3.connect(f"{backup_file.resolve().as_uri()}?mode=ro", uri=True)
        try:
            _copy_database(src, staged)
        finally:
            src.close()
        for extra in ("-wal", "-shm"):
            Path(str(live) + extra).unlink(missing_ok=True)
        os.replace(staged, live)
        logger.info("Banco restaurado a partir de %s", backup_file.name)
        return live, safety


class BackupScheduler:
    """Executa backups periódicos em uma thread de fundo (desligado se o intervalo for 0)."""

    def __init__(self, run: Callable[[], object], interval_s: float) -> None:
        self._run = run
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.interval_s <= 0 or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="backup-scheduler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._run()
            except Exception:  # noqa: BLE001 - uma falha não pode derrubar o agendador
                logger.exception("Falha no backup agendado")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
