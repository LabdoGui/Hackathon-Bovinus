import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import Limit, ManagerOperator, Offset, SearchQuery, SessionDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.ingredient import IngredientCreate, IngredientRead, IngredientUpdate
from app.services.catalog import IngredientService

router = APIRouter(prefix="/ingredients", tags=["Ingredientes"], responses=ERROR_RESPONSES)


@router.get("", response_model=Page[IngredientRead], summary="Listar ingredientes")
def list_ingredients(
    session: SessionDep, q: SearchQuery = None, active: bool | None = None, limit: Limit = 50, offset: Offset = 0
):
    items, total = IngredientService(session).list(query=q, active=active, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{ingredient_id}", response_model=IngredientRead, summary="Consultar ingrediente")
def get_ingredient(ingredient_id: uuid.UUID, session: SessionDep):
    return IngredientService(session).get(ingredient_id)


@router.post(
    "",
    response_model=IngredientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar ingrediente (gerente/admin)",
)
def create_ingredient(data: IngredientCreate, session: SessionDep, operator: ManagerOperator):
    return IngredientService(session).create(data, operator)


@router.patch("/{ingredient_id}", response_model=IngredientRead, summary="Alterar ingrediente (gerente/admin)")
def update_ingredient(ingredient_id: uuid.UUID, data: IngredientUpdate, session: SessionDep, operator: ManagerOperator):
    return IngredientService(session).update(ingredient_id, data, operator)


@router.delete(
    "/{ingredient_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir ingrediente (gerente/admin)"
)
def delete_ingredient(ingredient_id: uuid.UUID, session: SessionDep, operator: ManagerOperator) -> Response:
    IngredientService(session).delete(ingredient_id, operator)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
