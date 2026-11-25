"""Dependências compartilhadas das rotas: sessão do banco, configurações e acesso."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request, Security
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import OperatorRole
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import API_KEY_HEADER_NAME, api_key_header, role_satisfies
from app.models import Operator
from app.services.operators import OperatorService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.db.session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[Session, Depends(get_db)]


def get_current_operator(
    session: SessionDep,
    api_key: Annotated[str | None, Security(api_key_header)],
) -> Operator | None:
    """Operador identificado pela chave de API; ``None`` se nenhuma chave foi enviada."""
    if not api_key:
        return None
    operator = OperatorService(session).authenticate(api_key)
    if operator is None:
        raise AuthenticationError("Chave de API inválida ou operador inativo.")
    return operator


OptionalOperator = Annotated[Operator | None, Depends(get_current_operator)]


def require_role(role: OperatorRole):
    def dependency(operator: OptionalOperator) -> Operator:
        if operator is None:
            raise AuthenticationError(f"Informe a chave de API no cabeçalho {API_KEY_HEADER_NAME}.")
        if not role_satisfies(operator.role, role):
            raise PermissionDeniedError(f"Operação restrita ao perfil '{role.value}' ou superior.")
        return operator

    return dependency


CurrentOperator = Annotated[Operator, Depends(require_role(OperatorRole.OPERATOR))]
ManagerOperator = Annotated[Operator, Depends(require_role(OperatorRole.MANAGER))]
AdminOperator = Annotated[Operator, Depends(require_role(OperatorRole.ADMIN))]

Limit = Annotated[int, Query(ge=1, le=200, description="Quantidade máxima de itens")]
Offset = Annotated[int, Query(ge=0, le=1_000_000, description="Itens a pular")]
SearchQuery = Annotated[str | None, Query(max_length=100, description="Busca por nome")]
