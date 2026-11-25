import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import Limit, ManagerOperator, Offset, SearchQuery, SessionDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.recipe import RecipeCostRead, RecipeCreate, RecipeRead, RecipeUpdate
from app.services.catalog import RecipeService
from app.services.costing import recipe_cost_breakdown

router = APIRouter(prefix="/recipes", tags=["Fichas técnicas"], responses=ERROR_RESPONSES)


@router.get("", response_model=Page[RecipeRead], summary="Listar fichas técnicas")
def list_recipes(
    session: SessionDep, q: SearchQuery = None, active: bool | None = None, limit: Limit = 50, offset: Offset = 0
):
    items, total = RecipeService(session).list(query=q, active=active, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{recipe_id}", response_model=RecipeRead, summary="Consultar ficha técnica")
def get_recipe(recipe_id: uuid.UUID, session: SessionDep):
    return RecipeService(session).get(recipe_id)


@router.get("/{recipe_id}/cost", response_model=RecipeCostRead, summary="Custo estimado da ficha técnica")
def get_recipe_cost(recipe_id: uuid.UUID, session: SessionDep):
    return recipe_cost_breakdown(RecipeService(session).get(recipe_id))


@router.post(
    "", response_model=RecipeRead, status_code=status.HTTP_201_CREATED, summary="Cadastrar ficha técnica (gerente/admin)"
)
def create_recipe(data: RecipeCreate, session: SessionDep, operator: ManagerOperator):
    return RecipeService(session).create(data, operator)


@router.patch("/{recipe_id}", response_model=RecipeRead, summary="Alterar ficha técnica (gerente/admin)")
def update_recipe(recipe_id: uuid.UUID, data: RecipeUpdate, session: SessionDep, operator: ManagerOperator):
    return RecipeService(session).update(recipe_id, data, operator)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir ficha técnica (gerente/admin)")
def delete_recipe(recipe_id: uuid.UUID, session: SessionDep, operator: ManagerOperator) -> Response:
    RecipeService(session).delete(recipe_id, operator)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
