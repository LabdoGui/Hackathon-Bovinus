"""Inventário das rotas da API e do nível de acesso de cada uma.

Usado para gerar ``docs/endpoints.md`` e por um teste que impede que uma rota que altera dados
seja exposta sem controle de acesso por engano.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.api.router import API_PREFIX

ROLE_LABEL = {"operator": "operador", "manager": "gerente/admin", "admin": "admin"}
GROUP_ORDER = [
    "Sistema", "Operadores", "Ingredientes", "Fichas técnicas", "Alimentos", "Balança", "Câmera",
    "Reconhecimento", "Transações", "Relatórios", "Auditoria", "Administração",
]


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    summary: str
    tag: str
    access: str  # public | operator | manager | admin
    identifies_operator: bool  # aceita chave opcional (registra quem fez)


def _walk(routes) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes)


def _dependency_calls(dependant: Dependant) -> Iterator[object]:
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def route_access(route: APIRoute) -> tuple[str, bool]:
    calls = list(_dependency_calls(route.dependant))
    roles = [getattr(call, "required_role", None) for call in calls]
    roles = [r.value for r in roles if r is not None]
    order = ["operator", "manager", "admin"]
    if roles:
        return max(roles, key=order.index), True
    optional = any(getattr(c, "__name__", "") == "get_current_operator" for c in calls)
    return "public", optional


def collect_routes(app: FastAPI) -> list[RouteInfo]:
    found: list[RouteInfo] = []
    for route in _walk(app.routes):
        if not route.include_in_schema:  # páginas HTML etc.: fora da API
            continue
        path = API_PREFIX + route.path if not route.path.startswith(API_PREFIX) else route.path
        access, identifies = route_access(route)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append(
                RouteInfo(method, path, route.summary or route.name, (route.tags or ["Outros"])[0], access, identifies)
            )
    return sorted(found, key=lambda r: (GROUP_ORDER.index(r.tag) if r.tag in GROUP_ORDER else 99, r.path, r.method))


def render_endpoints_markdown(app: FastAPI) -> str:
    lines = [
        "# Endpoints da API (`/api/v1`)",
        "",
        "> Arquivo **gerado automaticamente** (`python -m app.cli docs`); não edite à mão. "
        "A documentação interativa completa está em `/docs` (Swagger) e `/redoc`.",
        "",
        "**Autenticação:** cabeçalho `X-API-Key` (chaves criadas com `python -m app.cli create-operator`). "
        "Perfis: `operador` < `gerente` < `admin`.",
        "",
        "**Acesso:** *público* = sem chave (a menos que `API_REQUIRE_KEY=true`; então todas as rotas, exceto "
        "`/health`, exigem chave); *público + chave opcional* = sem chave funciona, e com chave registra o operador.",
        "",
    ]
    current = None
    for info in collect_routes(app):
        if info.tag != current:
            current = info.tag
            lines += ["", f"## {current}", "", "| Método | Caminho | Descrição | Acesso |", "|---|---|---|---|"]
        if info.access == "public":
            access = "público + chave opcional" if info.identifies_operator else "público"
        else:
            access = ROLE_LABEL[info.access]
        summary = info.summary.replace("|", "\\|")
        lines.append(f"| {info.method} | `{info.path}` | {summary} | {access} |")
    lines.append("")
    return "\n".join(lines)
