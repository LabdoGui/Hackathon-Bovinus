import uuid
from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import RecognitionMode, RecognitionStatus
from app.schemas.common import ORMModel
from app.schemas.types import Grams, Ratio


class RecognitionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"image_capture_id": "00000000-0000-0000-0000-000000000000", "net_weight_g": 500}]}
    )

    image_capture_id: uuid.UUID = Field(description="Captura (câmera ou upload) a analisar.")
    scale_reading_id: uuid.UUID | None = Field(
        default=None, description="Leitura da balança: usa o peso líquido para estimar o peso de cada alimento."
    )
    net_weight_g: Grams | None = Field(
        default=None, description="Alternativa à leitura: peso líquido informado diretamente (g)."
    )

    @model_validator(mode="after")
    def _one_weight_source(self) -> Self:
        if self.scale_reading_id is not None and self.net_weight_g is not None:
            raise ValueError("Informe scale_reading_id OU net_weight_g, não ambos.")
        return self


class DetectionRead(BaseModel):
    """Alimento identificado."""

    name: str = Field(description="Nome do alimento.")
    recognition_class: str = Field(description="Classe retornada pelo reconhecimento.")
    confidence: Ratio = Field(description="Confiança (0 a 1).")
    segmented_area_px: int | None = Field(default=None, description="Área segmentada em pixels, quando disponível.")
    segmented_area_ratio: Ratio | None = Field(default=None, description="Fração da imagem ocupada, quando disponível.")
    proportion: Ratio = Field(description="Proporção estimada do prato (soma 1 entre os alimentos).")
    estimated_weight_g: Grams | None = Field(
        default=None, description="Peso estimado (proporção × peso líquido); vazio sem peso informado."
    )
    source: RecognitionMode = Field(description="Origem do resultado (mock, api ou local).")
    food_id: uuid.UUID | None = Field(default=None, description="Alimento cadastrado correspondente, se houver.")
    matched: bool
    review_reasons: list[str] = []


class RecognitionResultRead(ORMModel):
    id: uuid.UUID
    image_capture_id: uuid.UUID
    provider: RecognitionMode
    model_name: str | None
    model_version: str | None
    is_simulated: bool
    status: RecognitionStatus
    overall_confidence: Ratio | None
    requires_review: bool
    review_reasons: list[str]
    net_weight_g: Grams | None
    detections: list[DetectionRead]
    error: str | None
    processing_ms: int | None
    created_at: datetime
    notice: str | None = Field(
        default=None, description="Aviso obrigatório quando o resultado é simulado ou não há modelo."
    )


class RecognitionStatusRead(BaseModel):
    mode: RecognitionMode
    is_simulated: bool
    model_available: bool = Field(description="Verdadeiro somente se há um modelo/serviço real utilizável.")
    model_name: str | None
    min_confidence: Decimal
    details: dict
    message: str
