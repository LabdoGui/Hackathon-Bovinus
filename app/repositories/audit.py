from datetime import datetime

from sqlalchemy import select

from app.core.enums import AuditAction
from app.models import AuditLog, Operator
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

    def usernames(self, operator_ids: set) -> dict:
        if not operator_ids:
            return {}
        rows = self.session.execute(select(Operator.id, Operator.username).where(Operator.id.in_(operator_ids)))
        return {row.id: row.username for row in rows}

    def list(
        self,
        *,
        entity_type: str | None,
        entity_id: str | None,
        action: AuditAction | None,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditLog], int]:
        statement = select(AuditLog)
        if entity_type:
            statement = statement.where(AuditLog.entity_type == entity_type)
        if entity_id:
            statement = statement.where(AuditLog.entity_id == entity_id)
        if action is not None:
            statement = statement.where(AuditLog.action == action)
        if created_from is not None:
            statement = statement.where(AuditLog.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(AuditLog.created_at < created_to)
        return self.paginate(statement, limit=limit, offset=offset, order_by=[AuditLog.created_at.desc()])
