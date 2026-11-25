from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.enums import AuditAction, OperatorRole
from app.core.exceptions import ConflictError, NotFoundError
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
