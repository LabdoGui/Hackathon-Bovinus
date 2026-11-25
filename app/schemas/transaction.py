import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ItemSource, TransactionStatus
from app.schemas.common import ORMModel
from app.schemas.types import (
    _AS_NUMBER,
    Grams,
    LongText,
    Money,
    Percent,
    PositiveGrams,
    Ratio,
    SignedMoney,
    UnitCost,
    _quantizer,
)

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


class TransactionFromRecognition(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "recognition_result_id": "00000000-0000-0000-0000-000000000000",
                    "scale_reading_id": "00000000-0000-0000-0000-000000000001",
                }
            ]
        }
    )

    recognition_result_id: uuid.UUID = Field(description="Resultado de POST /recognition/analyze.")
    scale_reading_id: uuid.UUID = Field(description="Leitura estável da balança (POST /scale/readings).")
    price_per_kg: PricePerKg | None = Field(
        default=None, description="Preço cobrado por kg. Vazio = DEFAULT_PRICE_PER_KG da configuração."
    )
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
    reviewed_at: datetime | None
    reviewed_by_id: uuid.UUID | None
    items: list[TransactionItemRead]


class TransactionCancel(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class ReviewItemIn(BaseModel):
    """Item da transação após a correção do operador."""

    item_id: uuid.UUID | None = Field(
        default=None, description="Item existente a corrigir. Vazio = acrescentar um alimento que faltou."
    )
    food_id: uuid.UUID = Field(description="Alimento cadastrado correto.")
    proportion: PositiveRatio | None = Field(default=None, description="Proporção do prato (0 a 1).")
    weight_g: PositiveGrams | None = Field(default=None, description="Peso do alimento em gramas.")

    @model_validator(mode="after")
    def _exactly_one_measure(self) -> Self:
        if (self.proportion is None) == (self.weight_g is None):
            raise ValueError("Informe proportion OU weight_g em cada item.")
        return self


class TransactionReviewIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "reason": "Feijão estava identificado como farofa",
                    "items": [{"item_id": "00000000-0000-0000-0000-000000000000", "food_id": "00000000-0000-0000-0000-000000000001", "weight_g": 300}],
                    "confirm": True,
                }
            ]
        }
    )

    reason: Annotated[str, Field(min_length=3, max_length=500, description="Motivo da revisão (fica na auditoria).")]
    items: list[ReviewItemIn] | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description="Lista COMPLETA de itens após a correção; itens omitidos são removidos. "
        "Vazio = não alterar os itens (apenas confirmar).",
    )
    confirm: bool = Field(default=False, description="Confirma a transação após aplicar as correções.")
    notes: LongText | None = None

    @model_validator(mode="after")
    def _something_to_do(self) -> Self:
        if self.items is None and not self.confirm and self.notes is None:
            raise ValueError("Nada a fazer: envie items, notes ou confirm=true.")
        if self.items is not None:
            modes = {item.weight_g is not None for item in self.items}
            if len(modes) > 1:
                raise ValueError("Use o mesmo critério em todos os itens: só proportion ou só weight_g.")
            ids = [item.item_id for item in self.items if item.item_id is not None]
            if len(ids) != len(set(ids)):
                raise ValueError("O mesmo item_id aparece mais de uma vez.")
            foods = [item.food_id for item in self.items]
            if len(foods) != len(set(foods)):
                raise ValueError("O mesmo alimento não pode aparecer duas vezes; some as quantidades.")
        return self
