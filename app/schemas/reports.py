from datetime import date

from pydantic import BaseModel, Field

from app.schemas.types import Grams, Money, Percent, SignedMoney


class PeriodRead(BaseModel):
    date_from: date
    date_to: date
    timezone: str
    days: int


class SummaryRead(BaseModel):
    period: PeriodRead
    transactions_confirmed: int
    transactions_pending_review: int
    transactions_cancelled: int
    total_net_weight_g: Grams
    total_charged_amount: Money
    average_ticket: Money | None
    average_net_weight_g: Grams | None
    pending_review_charged_amount: Money = Field(description="Valor das transações ainda em revisão (não incluído nos totais).")
    cost_complete_transactions: int = Field(description="Transações confirmadas com custo conhecido para todos os itens.")
    cost_incomplete_transactions: int = Field(description="Transações confirmadas com algum item sem custo (fora da margem).")
    charged_amount_with_known_cost: Money = Field(description="Base da margem: valor cobrado das transações com custo completo.")
    total_food_cost: Money = Field(description="Custo alimentar estimado (somente transações com custo completo).")
    total_gross_margin: SignedMoney = Field(description="Margem bruta alimentar estimada (somente transações com custo completo).")
    gross_margin_pct: Percent | None
    notes: list[str]


class DayRow(BaseModel):
    date: date
    transactions: int
    net_weight_g: Grams
    charged_amount: Money
    food_cost: Money
    gross_margin: SignedMoney


class ByDayRead(BaseModel):
    period: PeriodRead
    days: list[DayRow]
    notes: list[str]


class FoodRow(BaseModel):
    food_id: str | None
    food_name: str
    transactions: int
    weight_g: Grams
    weight_share_pct: Percent
    known_cost: Money = Field(description="Custo estimado dos itens com custo conhecido.")
    items_without_cost: int
    average_cost_per_kg: Money | None


class ByFoodRead(BaseModel):
    period: PeriodRead
    foods: list[FoodRow]
    notes: list[str]


class ReasonCount(BaseModel):
    reason: str
    transactions: int


class ReviewStatsRead(BaseModel):
    period: PeriodRead
    transactions: int
    from_recognition: int
    simulated_recognition: int
    reviewed: int
    pending_review: int
    transactions_with_corrections: int
    recognition_items: int
    recognition_items_corrected: int
    recognition_correction_rate_pct: Percent | None = Field(
        description="% de itens vindos do reconhecimento que o operador precisou corrigir."
    )
    reasons: list[ReasonCount]
    notes: list[str]
