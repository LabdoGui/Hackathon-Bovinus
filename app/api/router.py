from fastapi import APIRouter, Depends

from app.api.deps import enforce_global_key
from app.api.routes import (
    admin,
    audit,
    camera,
    foods,
    health,
    ingredients,
    operators,
    recipes,
    recognition,
    reports,
    scale,
    transactions,
)

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
# /health fica sempre público (monitoramento); o restante exige chave se API_REQUIRE_KEY=true.
api_router.include_router(health.router)

protected = APIRouter(dependencies=[Depends(enforce_global_key)])
for module in (
    operators, ingredients, recipes, foods, transactions, scale, camera, recognition, reports, audit, admin,
):
    protected.include_router(module.router)
api_router.include_router(protected)
