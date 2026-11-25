"""Tipos numéricos reutilizáveis.

Entradas são convertidas para ``Decimal`` e arredondadas (ROUND_HALF_UP) para a
precisão de armazenamento; na saída JSON viram números.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, PlainSerializer, StringConstraints


def _quantizer(places: int) -> AfterValidator:
    quantum = Decimal(1).scaleb(-places)
    return AfterValidator(lambda value: value.quantize(quantum, rounding=ROUND_HALF_UP))


_AS_NUMBER = PlainSerializer(lambda value: float(value), return_type=float, when_used="json")

MAX_WEIGHT_G = Decimal("100000")  # 100 kg
MAX_MONEY = Decimal("100000000")

Grams = Annotated[Decimal, Field(ge=0, le=MAX_WEIGHT_G, allow_inf_nan=False), _quantizer(1), _AS_NUMBER]
PositiveGrams = Annotated[Decimal, Field(gt=0, le=MAX_WEIGHT_G, allow_inf_nan=False), _quantizer(1), _AS_NUMBER]
Money = Annotated[Decimal, Field(ge=0, le=MAX_MONEY, allow_inf_nan=False), _quantizer(2), _AS_NUMBER]
SignedMoney = Annotated[Decimal, Field(ge=-MAX_MONEY, le=MAX_MONEY, allow_inf_nan=False), _quantizer(2), _AS_NUMBER]
Percent = Annotated[Decimal, Field(allow_inf_nan=False), _quantizer(2), _AS_NUMBER]
UnitCost = Annotated[Decimal, Field(ge=0, le=MAX_MONEY, allow_inf_nan=False), _quantizer(4), _AS_NUMBER]
Quantity = Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), allow_inf_nan=False), _quantizer(4), _AS_NUMBER]
Ratio = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False), _quantizer(4), _AS_NUMBER]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
RecognitionClass = Annotated[
    str,
    BeforeValidator(lambda value: value.strip().lower() if isinstance(value, str) else value),
    StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$"),
]
