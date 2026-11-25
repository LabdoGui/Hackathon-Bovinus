import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ItemSource, TransactionStatus
from app.schemas.common import ORMModel
from app.schemas.types import _AS_NUMBER, Grams, LongText, Money, Percent, Ratio, SignedMoney, UnitCost, _quantizer

PROPORTION_TOLERANCE = Decimal("0.01")

PositiveRatio = Annotated[Decimal, Field(gt=0, le=1, allow_inf_nan=False), _quantizer(4), _AS_NUMBER]
PricePerKg = Annotated[Decimal, Field(gt=0, le=Decimal("100000"), allow_inf_nan=False), _quantizer(2), _AS_NUMBER]


class TransactionItemIn(BaseModel):
    food_id: uuid.UUID
    proportion: PositiveRatio = Field(description="Fração do prato ocupada pelo alimento (0 a 1).")


def _validate_items(items: list[TransactionItemIn]) -> None:
    ids = [item.food_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("O mesmo alimento não pode aparecer duas vezes; some as proporções.")
    total = sum((item.proportion for item in items), Decimal("0"))
    if abs(total - 1) > PROPORTION_TOLERANCE:
        raise ValueError(f"A soma das proporções deve ser 1 (±{PROPORTION_TOLERANCE}); recebido {total}.")


class _ItemsMixin(BaseModel):
    items: list[TransactionItemIn] = Field(min_length=1, max_length=30)
    price_per_kg: PricePerKg | None = Field(
        default=None, description="Preço cobrado por kg. Vazio = DEFAULT_PRICE_PER_KG da configuração."
    )

    @model_validator(mode="after")
    def _check_items(self) -> Self:
        _validate_items(self.items)
        return self


class TransactionCreate(_ItemsMixin):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "scale_reading_id": "00000000-0000-0000-0000-000000000000",
                    "items": [
                        {"food_id": "00000000-0000-0000-0000-000000000001", "proportion": 0.6},
                        {"food_id": "00000000-0000-0000-0000-000000000002", "proportion": 0.4},
                    ],
                }
            ]
        }
    )

    scale_reading_id: uuid.UUID = Field(description="Leitura estável da balança (POST /scale/readings).")
    notes: LongText | None = None


class CalculationPreviewIn(_ItemsMixin):
    gross_weight_g: Grams
    tare_g: Grams = Decimal("0")


class CalculationItemRead(BaseModel):
    food_id: uuid.UUID
    food_name: str
    proportion: Ratio
    weight_g: Grams
    cost_per_kg: UnitCost | None
    cost: Money | None


class CalculationRead(BaseModel):
    gross_weight_g: Grams
    tare_g: Grams
    net_weight_g: Grams
    price_per_kg: Money
    charged_amount: Money
    food_cost: Money | None = Field(description="Custo alimentar estimado (None se algum item não tiver ficha técnica).")
    known_food_cost: Money
    cost_complete: bool
    gross_margin: SignedMoney | None = Field(description="Margem bruta alimentar estimada = valor cobrado - custo.")
    gross_margin_pct: Percent | None
    requires_review: bool
    review_reasons: list[str]
    items: list[CalculationItemRead]


class TransactionItemRead(ORMModel):
    id: uuid.UUID
    position: int
    food_id: uuid.UUID | None
    food_name: str
    recognition_class: str | None
    source: ItemSource
    confidence: Ratio | None
    proportion: Ratio
    weight_g: Grams
    cost_per_kg: UnitCost | None
    cost: Money | None
    is_corrected: bool
    original_food_id: uuid.UUID | None
    original_food_name: str | None
    original_proportion: Ratio | None
    original_weight_g: Grams | None


class TransactionRead(ORMModel):
    id: uuid.UUID
    code: str
    status: TransactionStatus
    operator_id: uuid.UUID | None
    scale_reading_id: uuid.UUID | None
    image_capture_id: uuid.UUID | None
    recognition_result_id: uuid.UUID | None
    gross_weight_g: Grams
    tare_g: Grams
    net_weight_g: Grams
    price_per_kg: Money
    charged_amount: Money
    food_cost: Money | None
    gross_margin: SignedMoney | None
    gross_margin_pct: Percent | None
    requires_review: bool
    review_reasons: list[str]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    items: list[TransactionItemRead]


class TransactionCancel(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=500)]
