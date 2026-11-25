import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request

from app.api.deps import Limit, ManagerOperator, Offset, SessionDep
from app.core.enums import AuditAction
from app.schemas.audit import AuditLogRead
from app.schemas.common import ERROR_RESPONSES, Page
from app.services.audit_history import AuditHistoryService

router = APIRouter(prefix="/audit-logs", tags=["Auditoria"], responses=ERROR_RESPONSES)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


@router.get("", response_model=Page[AuditLogRead], summary="Consultar histórico de auditoria (gerente/admin)")
def list_audit_logs(
    session: SessionDep,
    _: ManagerOperator,
    entity_type: str | None = Query(default=None, max_length=50),
    entity_id: str | None = Query(default=None, max_length=64),
    action: AuditAction | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    items, total = AuditHistoryService(session).search(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        created_from=_aware(created_from),
        created_to=_aware(created_to),
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}
