"""Seed idempotente com dados FICTÍCIOS de demonstração.

Todos os registros criados aqui têm ``is_demo=True``, o sufixo "(demo)" no nome
e uma observação explícita. Preços e rendimentos são ilustrativos e não devem
ser usados para precificação real.

Executar mais de uma vez não duplica nem altera registros existentes: apenas
os itens ausentes (pelo nome) são criados.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditAction, IngredientUnit
from app.models import Food, Ingredient, Recipe, RecipeIngredient
from app.services.audit import AuditService
from app.utils.serialization import entity_snapshot

logger = logging.getLogger(__name__)

DEMO_NOTE = "DADO FICTÍCIO para demonstração. Valores não representam preços nem rendimentos reais."
SEED_REASON = "Seed de demonstração (dados fictícios)"

D = Decimal

# nome -> (unidade, custo por unidade em R$)
DEMO_INGREDIENTS: dict[str, tuple[IngredientUnit, Decimal]] = {
    "Arroz agulhinha (demo)": (IngredientUnit.KG, D("6.50")),
    "Feijão carioca (demo)": (IngredientUnit.KG, D("8.90")),
    "Óleo de soja (demo)": (IngredientUnit.LITER, D("8.50")),
    "Alho (demo)": (IngredientUnit.KG, D("32.00")),
    "Cebola (demo)": (IngredientUnit.KG, D("5.50")),
    "Sal refinado (demo)": (IngredientUnit.KG, D("3.00")),
    "Patinho bovino (demo)": (IngredientUnit.KG, D("44.90")),
    "Filé de peito de frango (demo)": (IngredientUnit.KG, D("23.90")),
    "Tomate (demo)": (IngredientUnit.KG, D("7.80")),
    "Alface crespa (demo)": (IngredientUnit.UNIT, D("3.50")),
    "Cenoura (demo)": (IngredientUnit.KG, D("5.20")),
    "Macarrão espaguete (demo)": (IngredientUnit.KG, D("9.80")),
    "Farinha de mandioca (demo)": (IngredientUnit.KG, D("8.40")),
    "Manteiga (demo)": (IngredientUnit.KG, D("48.00")),
    "Batata (demo)": (IngredientUnit.KG, D("5.90")),
    "Leite integral (demo)": (IngredientUnit.LITER, D("5.60")),
}

# nome -> (rendimento em g, [(ingrediente, quantidade bruta, quantidade líquida | None)])
DEMO_RECIPES: dict[str, tuple[Decimal, list[tuple[str, Decimal, Decimal | None]]]] = {
    "Arroz branco (demo)": (
        D("2600"),
        [
            ("Arroz agulhinha (demo)", D("1.0"), None),
            ("Óleo de soja (demo)", D("0.03"), None),
            ("Alho (demo)", D("0.02"), D("0.017")),
            ("Cebola (demo)", D("0.05"), D("0.045")),
            ("Sal refinado (demo)", D("0.015"), None),
        ],
    ),
    "Feijão carioca (demo)": (
        D("2800"),
        [
            ("Feijão carioca (demo)", D("1.0"), None),
            ("Cebola (demo)", D("0.1"), D("0.09")),
            ("Alho (demo)", D("0.02"), D("0.017")),
            ("Óleo de soja (demo)", D("0.03"), None),
            ("Sal refinado (demo)", D("0.02"), None),
        ],
    ),
    "Carne de panela (demo)": (
        D("1500"),
        [
            ("Patinho bovino (demo)", D("2.0"), D("1.8")),
            ("Cebola (demo)", D("0.2"), D("0.18")),
            ("Tomate (demo)", D("0.3"), D("0.27")),
            ("Alho (demo)", D("0.03"), D("0.025")),
            ("Óleo de soja (demo)", D("0.05"), None),
            ("Sal refinado (demo)", D("0.03"), None),
        ],
    ),
    "Frango grelhado (demo)": (
        D("1500"),
        [
            ("Filé de peito de frango (demo)", D("2.0"), D("1.9")),
            ("Alho (demo)", D("0.02"), D("0.017")),
            ("Óleo de soja (demo)", D("0.04"), None),
            ("Sal refinado (demo)", D("0.02"), None),
        ],
    ),
    "Salada verde (demo)": (
        D("1100"),
        [
            ("Alface crespa (demo)", D("3"), None),
            ("Tomate (demo)", D("0.5"), D("0.45")),
            ("Cenoura (demo)", D("0.3"), D("0.25")),
        ],
    ),
    "Macarrão alho e óleo (demo)": (
        D("2200"),
        [
            ("Macarrão espaguete (demo)", D("1.0"), None),
            ("Alho (demo)", D("0.06"), D("0.05")),
            ("Óleo de soja (demo)", D("0.1"), None),
            ("Sal refinado (demo)", D("0.02"), None),
        ],
    ),
    "Farofa simples (demo)": (
        D("620"),
        [
            ("Farinha de mandioca (demo)", D("0.5"), None),
            ("Manteiga (demo)", D("0.08"), None),
            ("Cebola (demo)", D("0.1"), D("0.09")),
            ("Sal refinado (demo)", D("0.008"), None),
        ],
    ),
    "Purê de batata (demo)": (
        D("2000"),
        [
            ("Batata (demo)", D("2.0"), D("1.7")),
            ("Leite integral (demo)", D("0.4"), None),
            ("Manteiga (demo)", D("0.08"), None),
            ("Sal refinado (demo)", D("0.015"), None),
        ],
    ),
}

# nome -> (classe de reconhecimento, categoria, ficha técnica | None)
DEMO_FOODS: dict[str, tuple[str, str, str | None]] = {
    "Arroz branco (demo)": ("arroz_branco", "Acompanhamento", "Arroz branco (demo)"),
    "Feijão carioca (demo)": ("feijao_carioca", "Acompanhamento", "Feijão carioca (demo)"),
    "Carne de panela (demo)": ("carne_de_panela", "Proteína", "Carne de panela (demo)"),
    "Frango grelhado (demo)": ("frango_grelhado", "Proteína", "Frango grelhado (demo)"),
    "Salada verde (demo)": ("salada_verde", "Salada", "Salada verde (demo)"),
    "Macarrão alho e óleo (demo)": ("macarrao_alho_oleo", "Massa", "Macarrão alho e óleo (demo)"),
    "Farofa simples (demo)": ("farofa", "Acompanhamento", "Farofa simples (demo)"),
    "Purê de batata (demo)": ("pure_de_batata", "Acompanhamento", "Purê de batata (demo)"),
    # Sem ficha técnica de propósito: exercita o fluxo de custo desconhecido / revisão.
    "Sobremesa do dia (demo)": ("sobremesa_do_dia", "Sobremesa", None),
}


@dataclass
class SeedReport:
    created: dict[str, int] = field(default_factory=lambda: {"ingredients": 0, "recipes": 0, "foods": 0})
    skipped: dict[str, int] = field(default_factory=lambda: {"ingredients": 0, "recipes": 0, "foods": 0})


def seed_demo_data(session: Session) -> SeedReport:
    report = SeedReport()
    audit = AuditService(session)

    def record(entity_type: str, entity) -> None:
        audit.record(
            entity_type=entity_type,
            entity_id=entity.id,
            action=AuditAction.CREATE,
            after=entity_snapshot(entity),
            reason=SEED_REASON,
        )

    ingredients = {i.name: i for i in session.scalars(select(Ingredient).where(Ingredient.name.in_(DEMO_INGREDIENTS)))}
    for name, (unit, unit_cost) in DEMO_INGREDIENTS.items():
        if name in ingredients:
            report.skipped["ingredients"] += 1
            continue
        ingredient = Ingredient(name=name, unit=unit, unit_cost=unit_cost, notes=DEMO_NOTE, is_demo=True)
        session.add(ingredient)
        session.flush()
        record("ingredient", ingredient)
        ingredients[name] = ingredient
        report.created["ingredients"] += 1

    recipes = {r.name: r for r in session.scalars(select(Recipe).where(Recipe.name.in_(DEMO_RECIPES)))}
    for name, (yield_g, items) in DEMO_RECIPES.items():
        if name in recipes:
            report.skipped["recipes"] += 1
            continue
        recipe = Recipe(name=name, description=DEMO_NOTE, yield_weight_g=yield_g, is_demo=True)
        recipe.ingredients = [
            RecipeIngredient(ingredient=ingredients[ing], gross_quantity=gross, net_quantity=net, position=index)
            for index, (ing, gross, net) in enumerate(items)
        ]
        session.add(recipe)
        session.flush()
        record("recipe", recipe)
        recipes[name] = recipe
        report.created["recipes"] += 1

    existing_foods = set(session.scalars(select(Food.name).where(Food.name.in_(DEMO_FOODS))))
    used_classes = set(session.scalars(select(Food.recognition_class)))
    for name, (recognition_class, category, recipe_name) in DEMO_FOODS.items():
        if name in existing_foods or recognition_class in used_classes:
            report.skipped["foods"] += 1
            continue
        food = Food(
            name=name,
            recognition_class=recognition_class,
            category=category,
            description=DEMO_NOTE,
            recipe=recipes.get(recipe_name) if recipe_name else None,
            is_demo=True,
        )
        session.add(food)
        session.flush()
        record("food", food)
        report.created["foods"] += 1

    session.commit()
    logger.info("Seed concluído: criados=%s ignorados=%s", report.created, report.skipped)
    return report
