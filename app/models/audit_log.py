import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AuditAction
from app.models.base import Base, CreatedAtMixin, JSONType, UUIDPrimaryKeyMixin, str_enum


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Registro de auditoria somente de inclusão (nunca é alterado ou removido pela API).

    ``before`` e ``after`` guardam o estado da entidade antes e depois da ação.
    Falhas de hardware também são registradas aqui (``entity_type='hardware'``).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[AuditAction] = mapped_column(str_enum(AuditAction, 24), nullable=False, index=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operators.id", ondelete="SET NULL"), index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    reason: Mapped[str | None] = mapped_column(String(500))
