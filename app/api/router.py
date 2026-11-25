from fastapi import APIRouter

from app.api.routes import (
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
for module in (health, operators, ingredients, recipes, foods, transactions, scale, camera, recognition, reports, audit):
    api_router.include_router(module.router)
