from sqlalchemy import select

from app.models import AuditLog
from app.repositories.base import Repository


class AuditLogRepository(Repository[AuditLog]):
    model = AuditLog

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[AuditLog]:
        statement = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at)
        )
        return list(self.session.scalars(statement))
