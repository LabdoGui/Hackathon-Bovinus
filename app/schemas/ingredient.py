import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import IngredientUnit
from app.schemas.common import ORMModel
from app.schemas.types import LongText, Name, UnitCost


class IngredientBase(BaseModel):
    name: Name
    unit: IngredientUnit = IngredientUnit.KG
    unit_cost: UnitCost
    notes: LongText | None = None
    is_demo: bool = False
    active: bool = True


class IngredientCreate(IngredientBase):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"name": "Arroz agulhinha tipo 1", "unit": "kg", "unit_cost": 6.5}]}
    )


class IngredientUpdate(BaseModel):
    name: Name | None = None
    unit: IngredientUnit | None = None
    unit_cost: UnitCost | None = None
    notes: LongText | None = None
    is_demo: bool | None = None
    active: bool | None = None


class IngredientRead(IngredientBase, ORMModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
