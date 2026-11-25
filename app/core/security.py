"""Chaves de API e hierarquia de papéis dos operadores.

As chaves são geradas aleatoriamente, exibidas uma única vez e armazenadas
somente como hash SHA-256 (as chaves têm alta entropia, então não é necessário
um hash lento como bcrypt).
"""

import hashlib
import secrets

from fastapi.security import APIKeyHeader

from app.core.enums import OperatorRole

API_KEY_HEADER_NAME = "X-API-Key"
API_KEY_PREFIX = "pc_"

api_key_header = APIKeyHeader(
    name=API_KEY_HEADER_NAME,
    auto_error=False,
    description="Chave de API do operador (gerada pelo comando `python -m app.cli create-operator`).",
)

_ROLE_LEVEL: dict[OperatorRole, int] = {
    OperatorRole.OPERATOR: 10,
    OperatorRole.MANAGER: 20,
    OperatorRole.ADMIN: 30,
}


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def role_satisfies(actual: OperatorRole, required: OperatorRole) -> bool:
    """Verdadeiro se o papel ``actual`` tem pelo menos as permissões de ``required``."""
    return _ROLE_LEVEL[actual] >= _ROLE_LEVEL[required]
