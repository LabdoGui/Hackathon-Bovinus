import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import ScaleMode
from app.schemas.common import ORMModel
from app.schemas.types import Grams, SignedGrams


class ScaleReadingCreate(BaseModel):
    source: ScaleMode | None = Field(
        default=None,
        description="Fonte da leitura. Vazio = balança configurada (SCALE_MODE). "
        "'mock' e 'manual' ficam disponíveis como alternativa quando habilitados.",
    )
    tare_g: Grams | None = Field(default=None, description="Tara desta leitura. Vazio = tara padrão atual.")
    simulated_weight_g: Grams | None = Field(
        default=None, description="Somente fonte 'mock': peso bruto do prato simulado."
    )
    manual_weight_g: Grams | None = Field(default=None, description="Somente fonte 'manual': peso bruto digitado.")


class ScaleReadingRead(ORMModel):
    id: uuid.UUID
    mode: ScaleMode
    gross_weight_g: Grams | None
    tare_g: Grams
    net_weight_g: SignedGrams | None = Field(description="Peso líquido = bruto - tara (pode ser negativo se a tara for maior).")
    stable: bool
    device: str | None
    error: str | None
    created_at: datetime
    min_weight_g: Grams
    valid_for_transaction: bool
    issues: list[str]


class TareUpdate(BaseModel):
    tare_g: Grams


class TareRead(BaseModel):
    tare_g: Grams


class StabilizationRead(BaseModel):
    samples: int
    tolerance_g: Grams
    timeout_s: float
    interval_ms: int


class ScaleStatusRead(BaseModel):
    configured_mode: ScaleMode
    available_sources: list[ScaleMode]
    device: dict
    tare_g: Grams
    min_weight_g: Grams
    stabilization: StabilizationRead
    mock_weight_g: Grams
    last_error: str | None


class SerialPortRead(BaseModel):
    device: str
    description: str
    hwid: str
