import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import OperatorRole
from app.schemas.common import ORMModel
from app.schemas.types import Name


class OperatorCreate(BaseModel):
    name: Name
    username: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9_.\-]+$")
    role: OperatorRole = OperatorRole.OPERATOR


class OperatorRead(ORMModel):
    id: uuid.UUID
    name: str
    username: str
    role: OperatorRole
    active: bool
    created_at: datetime


class OperatorCreated(OperatorRead):
    api_key: str = Field(description="Exibida somente nesta resposta. Guarde em local seguro.")


class OperatorUpdate(BaseModel):
    name: Name | None = None
    role: OperatorRole | None = None
    active: bool | None = None
