import random
from decimal import Decimal as D

import pytest

from app.services.calculations import (
    CalculationError,
    PlateItemInput,
    RecipeCostLine,
    calculate_plate,
    charged_amount,
    correction_factor,
    distribute_weight,
    gross_food_margin,
    item_cost,
    net_weight,
    normalize_proportions,
    recipe_cost,
)

# ------------------------------------------------------------- peso líquido


def test_net_weight_is_gross_minus_tare():
    assert net_weight(D("650"), D("150")) == D("500.0")
    assert net_weight(D("650.04"), D("150")) == D("500.0")
    assert net_weight(D("100"), D("100")) == D("0.0")


@pytest.mark.parametrize(("gross", "tare"), [(D("100"), D("150")), (D("-1"), D("0")), (D("10"), D("-1"))])
def test_net_weight_invalid(gross, tare):
    with pytest.raises(CalculationError):
        net_weight(gross, tare)


# ------------------------------------------------------- distribuição de peso


def test_distribution_sums_exactly_to_net_weight():
    assert distribute_weight(D("500.0"), [D(1), D(1), D(1)]) == [D("166.7"), D("166.7"), D("166.6")]
    assert distribute_weight(D("500"), [D("0.6"), D("0.4")]) == [D("300.0"), D("200.0")]
    assert distribute_weight(D("432.1"), [D(1)]) == [D("432.1")]
    assert distribute_weight(D("0"), [D("0.5"), D("0.5")]) == [D("0.0"), D("0.0")]


def test_distribution_accepts_unnormalized_proportions():
    assert distribute_weight(D("400"), [D(2), D(1), D(1)]) == [D("200.0"), D("100.0"), D("100.0")]


def test_distribution_property_random_cases():
    rng = random.Random(42)
    for _ in range(500):
        net = D(rng.randint(0, 20000)) / 10
        proportions = [D(rng.randint(1, 1000)) / 1000 for _ in range(rng.randint(1, 8))]
        weights = distribute_weight(net, proportions)
        assert sum(weights) == net
        assert all(w >= 0 and w == w.quantize(D("0.1")) for w in weights)
        total = sum(proportions)
        for weight, proportion in zip(weights, proportions, strict=True):
            assert abs(weight - net * proportion / total) < D("0.1")


def test_distribution_tie_break_is_deterministic():
    assert distribute_weight(D("0.2"), [D(1), D(1), D(1)]) == [D("0.1"), D("0.1"), D("0.0")]


@pytest.mark.parametrize("proportions", [[], [D(0), D(0)], [D("-0.1"), D("1.1")]])
def test_distribution_invalid_proportions(proportions):
    with pytest.raises(CalculationError):
        distribute_weight(D("100"), proportions)


def test_normalize_proportions_sums_to_one():
    normalized = normalize_proportions([D(1), D(1), D(1)])
    assert normalized == [D("0.3334"), D("0.3333"), D("0.3333")]
    assert sum(normalized) == D("1.0000")
    assert normalize_proportions([D("0.59"), D("0.40")]) == [D("0.5960"), D("0.4040")]


# -------------------------------------------------------------------- custo


def test_recipe_cost_uses_gross_quantities_and_yield():
    lines = [
        RecipeCostLine(D("1.0"), D("6.50")),
        RecipeCostLine(D("0.03"), D("8.50")),
        RecipeCostLine(D("0.02"), D("32.00")),
        RecipeCostLine(D("0.05"), D("5.50")),
        RecipeCostLine(D("0.015"), D("3.00")),
    ]
    cost = recipe_cost(lines, D("2600"))
    assert cost.total_cost == D("7.7150")
    assert cost.cost_per_kg == D("2.9673")  # 7,715 / 2,6 kg


def test_recipe_cost_requires_positive_yield():
    with pytest.raises(CalculationError):
        recipe_cost([RecipeCostLine(D(1), D(1))], D(0))


def test_correction_factor():
    assert correction_factor(D("2.0"), D("1.6")) == D("1.2500")
    assert correction_factor(D("1"), None) is None


def test_item_cost():
    assert item_cost(D("250"), D("2.9673")) == D("0.74")
    assert item_cost(D("0"), D("50")) == D("0.00")


def test_charged_amount_rounds_half_up():
    assert charged_amount(D("500"), D("59.90")) == D("29.95")
    assert charged_amount(D("333.3"), D("59.90")) == D("19.96")
    assert charged_amount(D("500"), D("0.01")) == D("0.01")  # 0,005 -> 0,01 (meio para cima)


# ------------------------------------------------------------------- margem


def test_gross_food_margin():
    margin, pct = gross_food_margin(D("29.95"), D("11.09"))
    assert margin == D("18.86")
    assert pct == D("62.97")


def test_gross_food_margin_can_be_negative_and_handles_zero_charge():
    assert gross_food_margin(D("10.00"), D("12.50")) == (D("-2.50"), D("-25.00"))
    assert gross_food_margin(D("0"), D("1")) == (D("-1.00"), None)


# ------------------------------------------------------------- prato inteiro


def test_calculate_plate_complete():
    result = calculate_plate(
        gross_weight_g=D("650"),
        tare_g=D("150"),
        price_per_kg=D("59.90"),
        items=[PlateItemInput(D("0.6"), D("2.9673")), PlateItemInput(D("0.4"), D("40.00"))],
    )
    assert result.net_weight_g == D("500.0")
    assert [i.weight_g for i in result.items] == [D("300.0"), D("200.0")]
    assert sum(i.weight_g for i in result.items) == result.net_weight_g
    assert [i.cost for i in result.items] == [D("0.89"), D("8.00")]
    assert result.food_cost == D("8.89")
    assert result.charged_amount == D("29.95")
    assert result.gross_margin == D("21.06")
    assert result.gross_margin_pct == D("70.32")
    assert result.cost_complete


def test_calculate_plate_with_unknown_cost():
    result = calculate_plate(
        gross_weight_g=D("500"),
        tare_g=D("0"),
        price_per_kg=D("50"),
        items=[PlateItemInput(D("0.5"), D("10")), PlateItemInput(D("0.5"), None)],
    )
    assert not result.cost_complete
    assert result.food_cost is None and result.gross_margin is None and result.gross_margin_pct is None
    assert result.known_food_cost == D("2.50")
    assert result.items[1].cost is None
