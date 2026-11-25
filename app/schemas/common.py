from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(ge=0)
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Alimento não encontrado."])
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Requisição inválida"},
    401: {"model": ErrorResponse, "description": "Chave de API ausente ou inválida"},
    403: {"model": ErrorResponse, "description": "Sem permissão"},
    404: {"model": ErrorResponse, "description": "Recurso não encontrado"},
    409: {"model": ErrorResponse, "description": "Conflito (duplicidade ou recurso em uso)"},
    422: {"model": ErrorResponse, "description": "Dados inválidos"},
}
