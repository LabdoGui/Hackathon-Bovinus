from fastapi import APIRouter, status

from app.api.deps import AdminOperator, CurrentOperator, Limit, Offset, SessionDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.operator import OperatorCreate, OperatorCreated, OperatorRead
from app.services.operators import OperatorService

router = APIRouter(prefix="/operators", tags=["Operadores"], responses=ERROR_RESPONSES)


@router.get("/me", response_model=OperatorRead, summary="Operador autenticado")
def me(operator: CurrentOperator):
    return operator


@router.get("", response_model=Page[OperatorRead], summary="Listar operadores (admin)")
def list_operators(session: SessionDep, _: AdminOperator, limit: Limit = 50, offset: Offset = 0):
    items, total = OperatorService(session).list(limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post(
    "", response_model=OperatorCreated, status_code=status.HTTP_201_CREATED, summary="Criar operador (admin)"
)
def create_operator(data: OperatorCreate, session: SessionDep, admin: AdminOperator):
    operator, api_key = OperatorService(session).create(
        name=data.name, username=data.username, role=data.role, created_by=admin
    )
    return OperatorCreated.model_validate({**OperatorRead.model_validate(operator).model_dump(), "api_key": api_key})
