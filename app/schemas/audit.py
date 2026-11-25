import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.enums import AuditAction


class AuditLogRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    entity_type: str
    entity_id: str | None
    action: AuditAction
    operator_id: uuid.UUID | None
    operator_username: str | None
    reason: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
