import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import Limit, ManagerOperator, Offset, SearchQuery, SessionDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.food import FoodCreate, FoodRead, FoodUpdate
from app.services.catalog import FoodService

router = APIRouter(prefix="/foods", tags=["Alimentos"], responses=ERROR_RESPONSES)


@router.get("", response_model=Page[FoodRead], summary="Listar alimentos")
def list_foods(
    session: SessionDep,
    q: SearchQuery = None,
    active: bool | None = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    items, total = FoodService(session).list(query=q, active=active, category=category, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{food_id}", response_model=FoodRead, summary="Consultar alimento")
def get_food(food_id: uuid.UUID, session: SessionDep):
    return FoodService(session).get(food_id)


@router.post("", response_model=FoodRead, status_code=status.HTTP_201_CREATED, summary="Cadastrar alimento (gerente/admin)")
def create_food(data: FoodCreate, session: SessionDep, operator: ManagerOperator):
    return FoodService(session).create(data, operator)


@router.patch("/{food_id}", response_model=FoodRead, summary="Alterar alimento (gerente/admin)")
def update_food(food_id: uuid.UUID, data: FoodUpdate, session: SessionDep, operator: ManagerOperator):
    return FoodService(session).update(food_id, data, operator)


@router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir alimento (gerente/admin)")
def delete_food(food_id: uuid.UUID, session: SessionDep, operator: ManagerOperator) -> Response:
    FoodService(session).delete(food_id, operator)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
