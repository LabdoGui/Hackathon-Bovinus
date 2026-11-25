"""Consulta ao histórico de auditoria."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.repositories.audit import AuditLogRepository


class AuditHistoryService:
    def __init__(self, session: Session) -> None:
        self.repository = AuditLogRepository(session)

    def _views(self, logs: list[AuditLog]) -> list[dict[str, Any]]:
        names = self.repository.usernames({log.operator_id for log in logs if log.operator_id})
        return [
            {
                "id": log.id,
                "created_at": log.created_at,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "action": log.action,
                "operator_id": log.operator_id,
                "operator_username": names.get(log.operator_id),
                "reason": log.reason,
                "before": log.before,
                "after": log.after,
            }
            for log in logs
        ]

    def for_entity(self, entity_type: str, entity_id: uuid.UUID | str) -> list[dict[str, Any]]:
        return self._views(self.repository.list_for_entity(entity_type, str(entity_id)))

    def search(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        logs, total = self.repository.list(**filters)
        return self._views(logs), total
