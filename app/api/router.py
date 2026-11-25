from fastapi import APIRouter

from app.api.routes import (
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
for module in (health, operators, ingredients, recipes, foods, transactions, scale, camera, recognition, reports):
    api_router.include_router(module.router)
