from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.enums import AuditAction, OperatorRole
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.security import generate_api_key, hash_api_key
from app.models import Operator
from app.repositories.operator import OperatorRepository
from app.services.audit import AuditService
from app.utils.serialization import entity_snapshot


class OperatorService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OperatorRepository(session)
        self.audit = AuditService(session)

    def authenticate(self, api_key: str) -> Operator | None:
        """Retorna o operador ativo dono da chave, ou ``None``."""
        if not api_key:
            return None
        operator = self.repository.get_by_api_key_hash(hash_api_key(api_key))
        if operator is None or not operator.active:
            return None
        return operator

    def get(self, operator_id: uuid.UUID) -> Operator:
        operator = self.repository.get(operator_id)
        if operator is None:
            raise NotFoundError("Operador não encontrado.")
        return operator

    def list(self, *, limit: int, offset: int) -> tuple[list[Operator], int]:
        return self.repository.list(limit=limit, offset=offset)

    def create(
        self, *, name: str, username: str, role: OperatorRole, created_by: Operator | None = None
    ) -> tuple[Operator, str]:
        """Cria um operador e devolve a chave de API em texto puro (única vez em que ela existe)."""
        if self.repository.get_by_username(username):
            raise ConflictError(f"Usuário '{username}' já existe.")
        api_key = generate_api_key()
        operator = self.repository.add(
            Operator(name=name, username=username, role=role, api_key_hash=hash_api_key(api_key))
        )
        self.audit.record(
            entity_type="operator",
            entity_id=operator.id,
            action=AuditAction.CREATE,
            operator_id=created_by.id if created_by else None,
            after=entity_snapshot(operator, exclude=("api_key_hash",)),
        )
        self.session.commit()
        return operator, api_key

    def update(self, operator_id: uuid.UUID, *, changes: dict, changed_by: Operator | None) -> Operator:
        """Altera nome, perfil ou situação. Nunca deixa o sistema sem administrador ativo."""
        operator = self.get(operator_id)
        if "name" in changes and changes["name"] is None or "role" in changes and changes["role"] is None or (
            "active" in changes and changes["active"] is None
        ):
            raise BusinessRuleError("Campos obrigatórios não podem ser nulos.")
        will_lose_admin = operator.role is OperatorRole.ADMIN and operator.active and (
            changes.get("role", operator.role) is not OperatorRole.ADMIN or changes.get("active", operator.active) is False
        )
        if will_lose_admin and self.repository.count_active_admins(excluding=operator.id) == 0:
            raise ConflictError(
                "Não é possível remover o último administrador ativo.", code="last_admin_protected"
            )
        before = entity_snapshot(operator, exclude=("api_key_hash",))
        for key, value in changes.items():
            setattr(operator, key, value)
        self.session.flush()
        self.audit.record(
            entity_type="operator",
            entity_id=operator.id,
            action=AuditAction.UPDATE,
            operator_id=changed_by.id if changed_by else None,
            before=before,
            after=entity_snapshot(operator, exclude=("api_key_hash",)),
        )
        self.session.commit()
        return operator

    def rotate_key(self, operator_id: uuid.UUID, *, changed_by: Operator | None) -> tuple[Operator, str]:
        """Gera nova chave (a anterior deixa de valer imediatamente). Devolve a chave uma única vez."""
        operator = self.get(operator_id)
        api_key = generate_api_key()
        operator.api_key_hash = hash_api_key(api_key)
        self.audit.record(
            entity_type="operator",
            entity_id=operator.id,
            action=AuditAction.UPDATE,
            operator_id=changed_by.id if changed_by else None,
            reason="Chave de API rotacionada",
        )
        self.session.commit()
        return operator, api_key
