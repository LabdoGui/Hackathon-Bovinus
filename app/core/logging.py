"""Configuração de logs com remoção de dados sensíveis.

Toda mensagem passa pelo ``RedactingFilter``, que mascara chaves de API,
senhas e tokens antes de gravar no console ou em arquivo.
"""

import logging
import re
from contextvars import ContextVar
from logging.config import dictConfig

from app.core.config import Settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_KEY_VALUE = re.compile(
    r"(?i)\b(x-api-key|api[_-]?key|authorization|password|passwd|senha|secret|token)\b"
    r"(\"?\s*[:=]\s*\"?\s*(?:bearer\s+)?)([^\s\"',;&]+)"
)
_API_KEY_LITERAL = re.compile(r"\bpc_[A-Za-z0-9_\-]{16,}")
_URL_CREDENTIALS = re.compile(r"(\w+://[^:/\s]+:)([^@\s]+)(@)")


def redact(text: str) -> str:
    """Mascara valores sensíveis em um texto de log."""
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    text = _API_KEY_LITERAL.sub("pc_***", text)
    return _URL_CREDENTIALS.sub(r"\1***\3", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - nunca derrubar a aplicação por causa de log
            return True
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def setup_logging(settings: Settings) -> None:
    handlers: dict[str, dict] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["redact"],
        }
    }
    if settings.log_to_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filters": ["redact"],
            "filename": str(settings.log_dir / "pratocusto.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"redact": {"()": RedactingFilter}},
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
                }
            },
            "handlers": handlers,
            "root": {"level": settings.log_level, "handlers": list(handlers)},
            "loggers": {
                # O log de acesso do uvicorn inclui query strings; usamos o nosso próprio.
                "uvicorn.access": {"level": "WARNING", "propagate": True, "handlers": []},
                "uvicorn.error": {"propagate": True, "handlers": []},
                "uvicorn": {"propagate": True, "handlers": []},
                "sqlalchemy.engine": {"level": "INFO" if settings.db_echo else "WARNING"},
            },
        }
    )
