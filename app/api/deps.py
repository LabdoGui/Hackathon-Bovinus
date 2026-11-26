"""Dependências compartilhadas das rotas: sessão do banco, configurações e acesso."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request, Security
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import OperatorRole
from app.core.exceptions import AuthenticationError, PermissionDeniedError, TooManyRequestsError
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


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def get_current_operator(
    request: Request,
    session: SessionDep,
    api_key: Annotated[str | None, Security(api_key_header)],
) -> Operator | None:
    """Operador identificado pela chave de API; ``None`` se nenhuma chave foi enviada.

    Chaves inválidas são contadas por origem: acima do limite a origem é bloqueada
    temporariamente (429), o que inviabiliza adivinhar chaves por força bruta.
    """
    if not api_key:
        return None
    limiter = request.app.state.auth_limiter
    origin = _client_key(request)
    wait = limiter.retry_after(origin)
    if wait:
        raise TooManyRequestsError(
            "Muitas tentativas com chave inválida. Aguarde antes de tentar novamente.", retry_after=wait
        )
    operator = OperatorService(session).authenticate(api_key)
    if operator is None:
        limiter.record_failure(origin)
        raise AuthenticationError("Chave de API inválida ou operador inativo.")
    limiter.reset(origin)
    return operator


OptionalOperator = Annotated[Operator | None, Depends(get_current_operator)]


def require_role(role: OperatorRole):
    def dependency(operator: OptionalOperator) -> Operator:
        if operator is None:
            raise AuthenticationError(f"Informe a chave de API no cabeçalho {API_KEY_HEADER_NAME}.")
        if not role_satisfies(operator.role, role):
            raise PermissionDeniedError(f"Operação restrita ao perfil '{role.value}' ou superior.")
        return operator

    dependency.required_role = role  # type: ignore[attr-defined]  # usado pelo inventário de rotas
    return dependency


CurrentOperator = Annotated[Operator, Depends(require_role(OperatorRole.OPERATOR))]
ManagerOperator = Annotated[Operator, Depends(require_role(OperatorRole.MANAGER))]
AdminOperator = Annotated[Operator, Depends(require_role(OperatorRole.ADMIN))]

def enforce_global_key(operator: OptionalOperator, settings: SettingsDep) -> None:
    """Com API_REQUIRE_KEY=true, toda rota (exceto /health) exige uma chave válida."""
    if settings.api_require_key and operator is None:
        raise AuthenticationError(f"Informe a chave de API no cabeçalho {API_KEY_HEADER_NAME}.")


Limit = Annotated[int, Query(ge=1, le=200, description="Quantidade máxima de itens")]
Offset = Annotated[int, Query(ge=0, le=1_000_000, description="Itens a pular")]
SearchQuery = Annotated[str | None, Query(max_length=100, description="Busca por nome")]
