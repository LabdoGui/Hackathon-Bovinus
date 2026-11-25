"""Conversão de entidades ORM em dicionários seguros para JSON (auditoria)."""

import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import inspect


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    return value


def entity_snapshot(entity: Any, *, exclude: Iterable[str] = ()) -> dict[str, Any]:
    """Valores das colunas de uma entidade, sem relacionamentos."""
    skip = set(exclude)
    mapper = inspect(entity).mapper
    return {attr.key: json_safe(getattr(entity, attr.key)) for attr in mapper.column_attrs if attr.key not in skip}
