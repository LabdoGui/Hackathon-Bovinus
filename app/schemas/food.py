import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel
from app.schemas.recipe import RecipeSummary
from app.schemas.types import LongText, Name, RecognitionClass, ShortText


class FoodBase(BaseModel):
    name: Name
    recognition_class: RecognitionClass = Field(
        description="Rótulo do reconhecimento (minúsculas, números e '_'), ex.: arroz_branco."
    )
    category: ShortText | None = None
    description: LongText | None = None
    recipe_id: uuid.UUID | None = None
    is_demo: bool = False
    active: bool = True


class FoodCreate(FoodBase):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"name": "Arroz branco", "recognition_class": "arroz_branco", "category": "Acompanhamento"}]
        }
    )


class FoodUpdate(BaseModel):
    name: Name | None = None
    recognition_class: RecognitionClass | None = None
    category: ShortText | None = None
    description: LongText | None = None
    recipe_id: uuid.UUID | None = None
    is_demo: bool | None = None
    active: bool | None = None


class FoodRead(FoodBase, ORMModel):
    id: uuid.UUID
    recipe: RecipeSummary | None
    created_at: datetime
    updated_at: datetime
