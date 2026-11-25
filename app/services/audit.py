import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import AuditAction
from app.models import AuditLog


class AuditService:
    """Registra ações no histórico de auditoria, dentro da mesma transação do banco."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID | str | None,
        action: AuditAction,
        operator_id: uuid.UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            action=action,
            operator_id=operator_id,
            before=before,
            after=after,
            reason=reason[:500] if reason else None,
        )
        self.session.add(entry)
        return entry
