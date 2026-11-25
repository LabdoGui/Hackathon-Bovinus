"""Motor de cálculo do PratoCusto AI.

Funções puras, sem acesso a banco, balança, câmera ou reconhecimento. Todos os
valores são ``Decimal`` e os arredondamentos usam ROUND_HALF_UP.

Precisões:
* pesos: 0,1 g
* proporções: 0,0001
* custos unitários e custo por kg: R$ 0,0001
* valores monetários finais: R$ 0,01
* percentuais: 0,01 ponto percentual
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.core.exceptions import BusinessRuleError

WEIGHT_QUANTUM = Decimal("0.1")
RATIO_QUANTUM = Decimal("0.0001")
COST_QUANTUM = Decimal("0.0001")
MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")
GRAMS_PER_KG = Decimal("1000")
ZERO = Decimal("0")


class CalculationError(BusinessRuleError):
    code = "calculation_error"


def _round(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------- pesos


def net_weight(gross_weight_g: Decimal, tare_g: Decimal) -> Decimal:
    """Peso líquido = peso bruto - tara."""
    if gross_weight_g < 0 or tare_g < 0:
        raise CalculationError("Peso bruto e tara não podem ser negativos.")
    net = _round(gross_weight_g, WEIGHT_QUANTUM) - _round(tare_g, WEIGHT_QUANTUM)
    if net < 0:
        raise CalculationError(
            "A tara é maior que o peso bruto.", details={"gross_weight_g": str(gross_weight_g), "tare_g": str(tare_g)}
        )
    return net


def _validate_weights(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise CalculationError("Informe ao menos um alimento.")
    if any(value < 0 for value in values):
        raise CalculationError("Proporções não podem ser negativas.")
    total = sum(values, ZERO)
    if total <= 0:
        raise CalculationError("A soma das proporções deve ser maior que zero.")
    return total


def _largest_remainder(total_units: int, weights: Sequence[Decimal]) -> list[int]:
    """Divide ``total_units`` inteiros proporcionalmente a ``weights``.

    Método do maior resto: a soma do resultado é sempre exatamente
    ``total_units``. Empates são resolvidos pela ordem dos itens (determinístico).
    """
    total_weight = _validate_weights(weights)
    exact = [weight * total_units / total_weight for weight in weights]
    floors = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    leftover = total_units - sum(floors)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for index in order[:leftover]:
        floors[index] += 1
    return floors


def normalize_proportions(proportions: Sequence[Decimal]) -> list[Decimal]:
    """Normaliza proporções para somarem exatamente 1,0000."""
    units = _largest_remainder(int(1 / RATIO_QUANTUM), proportions)
    return [Decimal(unit) * RATIO_QUANTUM for unit in units]


def distribute_weight(net_weight_g: Decimal, proportions: Sequence[Decimal]) -> list[Decimal]:
    """Distribui o peso líquido entre os alimentos conforme as proporções.

    A soma dos pesos individuais é exatamente igual ao peso líquido (em 0,1 g).
    """
    if net_weight_g < 0:
        raise CalculationError("Peso líquido não pode ser negativo.")
    total_units = int(_round(net_weight_g, WEIGHT_QUANTUM) / WEIGHT_QUANTUM)
    units = _largest_remainder(total_units, proportions)
    return [Decimal(unit) * WEIGHT_QUANTUM for unit in units]


# --------------------------------------------------------------------- custos


@dataclass(frozen=True)
class RecipeCostLine:
    gross_quantity: Decimal  # na unidade do ingrediente (kg, l ou un)
    unit_cost: Decimal  # R$ por unidade do ingrediente


@dataclass(frozen=True)
class RecipeCost:
    total_cost: Decimal
    yield_weight_g: Decimal
    cost_per_kg: Decimal


def ingredient_line_cost(line: RecipeCostLine) -> Decimal:
    return _round(line.gross_quantity * line.unit_cost, COST_QUANTUM)


def recipe_cost(lines: Iterable[RecipeCostLine], yield_weight_g: Decimal) -> RecipeCost:
    """Custo da ficha técnica: soma (quantidade bruta x custo unitário) / rendimento."""
    if yield_weight_g <= 0:
        raise CalculationError("O rendimento da ficha técnica deve ser maior que zero.")
    lines = list(lines)
    if any(line.gross_quantity < 0 or line.unit_cost < 0 for line in lines):
        raise CalculationError("Quantidades e custos não podem ser negativos.")
    total = sum((line.gross_quantity * line.unit_cost for line in lines), ZERO)
    return RecipeCost(
        total_cost=_round(total, COST_QUANTUM),
        yield_weight_g=yield_weight_g,
        cost_per_kg=_round(total * GRAMS_PER_KG / yield_weight_g, COST_QUANTUM),
    )


def correction_factor(gross_quantity: Decimal, net_quantity: Decimal | None) -> Decimal | None:
    """Fator de correção (bruto / líquido) do pré-preparo."""
    if net_quantity is None or net_quantity <= 0:
        return None
    return _round(gross_quantity / net_quantity, COST_QUANTUM)


def item_cost(weight_g: Decimal, cost_per_kg: Decimal) -> Decimal:
    return _round(weight_g * cost_per_kg / GRAMS_PER_KG, MONEY_QUANTUM)


def charged_amount(net_weight_g: Decimal, price_per_kg: Decimal) -> Decimal:
    """Valor cobrado = peso líquido (kg) x preço por kg."""
    if price_per_kg < 0:
        raise CalculationError("O preço por kg não pode ser negativo.")
    return _round(net_weight_g * price_per_kg / GRAMS_PER_KG, MONEY_QUANTUM)


def gross_food_margin(charged: Decimal, food_cost: Decimal) -> tuple[Decimal, Decimal | None]:
    """Margem bruta alimentar estimada (R$ e % sobre o valor cobrado).

    Considera apenas o custo dos alimentos; não é lucro líquido.
    """
    margin = _round(charged - food_cost, MONEY_QUANTUM)
    if charged <= 0:
        return margin, None
    return margin, _round(margin * 100 / charged, PERCENT_QUANTUM)


# ---------------------------------------------------------------- prato inteiro


@dataclass(frozen=True)
class PlateItemInput:
    proportion: Decimal
    cost_per_kg: Decimal | None  # None quando o alimento não tem ficha técnica


@dataclass(frozen=True)
class PlateItemResult:
    proportion: Decimal
    weight_g: Decimal
    cost_per_kg: Decimal | None
    cost: Decimal | None


@dataclass(frozen=True)
class PlateCalculation:
    gross_weight_g: Decimal
    tare_g: Decimal
    net_weight_g: Decimal
    price_per_kg: Decimal
    charged_amount: Decimal
    items: list[PlateItemResult]
    known_food_cost: Decimal  # soma dos itens com custo conhecido
    cost_complete: bool
    food_cost: Decimal | None  # None se algum item não tiver custo
    gross_margin: Decimal | None
    gross_margin_pct: Decimal | None


def _assemble(
    *,
    gross: Decimal,
    tare: Decimal,
    net: Decimal,
    price_per_kg: Decimal,
    proportions: Sequence[Decimal],
    weights: Sequence[Decimal],
    costs: Sequence[Decimal | None],
) -> PlateCalculation:
    results = []
    for proportion, weight, cost_per_kg in zip(proportions, weights, costs, strict=True):
        cost = item_cost(weight, cost_per_kg) if cost_per_kg is not None else None
        results.append(PlateItemResult(proportion, weight, cost_per_kg, cost))

    known = sum((r.cost for r in results if r.cost is not None), ZERO)
    complete = all(r.cost is not None for r in results)
    charged = charged_amount(net, price_per_kg)
    food_cost = known if complete else None
    margin, margin_pct = gross_food_margin(charged, food_cost) if food_cost is not None else (None, None)

    return PlateCalculation(
        gross_weight_g=_round(gross, WEIGHT_QUANTUM),
        tare_g=_round(tare, WEIGHT_QUANTUM),
        net_weight_g=net,
        price_per_kg=price_per_kg,
        charged_amount=charged,
        items=results,
        known_food_cost=known,
        cost_complete=complete,
        food_cost=food_cost,
        gross_margin=margin,
        gross_margin_pct=margin_pct,
    )


def calculate_plate(
    *,
    gross_weight_g: Decimal,
    tare_g: Decimal,
    price_per_kg: Decimal,
    items: Sequence[PlateItemInput],
) -> PlateCalculation:
    """Calcula o prato a partir das proporções dos alimentos."""
    net = net_weight(gross_weight_g, tare_g)
    proportions = normalize_proportions([item.proportion for item in items])
    weights = distribute_weight(net, proportions)
    return _assemble(
        gross=gross_weight_g,
        tare=tare_g,
        net=net,
        price_per_kg=price_per_kg,
        proportions=proportions,
        weights=weights,
        costs=[item.cost_per_kg for item in items],
    )


def calculate_plate_from_weights(
    *,
    gross_weight_g: Decimal,
    tare_g: Decimal,
    price_per_kg: Decimal,
    weights_g: Sequence[Decimal],
    costs_per_kg: Sequence[Decimal | None],
) -> PlateCalculation:
    """Calcula o prato a partir do peso de cada alimento (correção do operador).

    Se a soma dos pesos informados for igual ao peso líquido, eles são mantidos
    exatamente. Se diferir um pouco (o chamador valida a tolerância), os pesos são
    escalados para somarem o peso líquido, mantendo as proporções entre eles.
    """
    net = net_weight(gross_weight_g, tare_g)
    weights = distribute_weight(net, [_round(w, WEIGHT_QUANTUM) for w in weights_g])
    return _assemble(
        gross=gross_weight_g,
        tare=tare_g,
        net=net,
        price_per_kg=price_per_kg,
        proportions=normalize_proportions(weights_g),
        weights=weights,
        costs=costs_per_kg,
    )
