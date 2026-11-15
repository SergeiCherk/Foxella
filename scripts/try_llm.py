"""Make a real request to the configured LLM and show how our validation treats the answer.

Usage: uv run python scripts/try_llm.py [breakfast|lunch|dinner|snack] [kcal]

Reads LLM_API_KEY, LLM_BASE_URL, LLM_MODEL (and optionally LLM_EXTRA_BODY) from .env.
It costs one or two cheap requests. Without a key it explains what is missing.
"""

import argparse
import asyncio
import sys

from nutrition_bot.config import get_settings
from nutrition_bot.core.errors import InvalidLLMResponseError, LLMError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import DishRequest, MealResult, build_meal, parse_dishes
from nutrition_bot.core.models import FoodState, MealType, Nutrients
from nutrition_bot.db.seed import catalog_from_rows, load_foods, load_measures
from nutrition_bot.services.llm import FakeLLM, build_llm

RAW_PREVIEW_CHARS = 1500


def describe(result: MealResult, catalog: Catalog) -> str:
    """Human-readable summary of a finished meal."""
    lines = [
        f"source: {result.source.value}, LLM calls: {result.attempts}",
        f"last problems: {list(result.problems) or 'none'}",
        f"total: {result.nutrients.kcal:.0f} kcal, protein {result.nutrients.protein_g:.0f} g, "
        f"fat {result.nutrients.fat_g:.0f} g, carbs {result.nutrients.carb_g:.0f} g",
    ]
    for dish in result.meal.dishes:
        lines.append(f"\n* {dish.name}\n  {dish.recipe_text}")
        for item in dish.items:
            food = catalog.get_food(item.food_id)
            measure = catalog.get_measure(item.food_id, item.measure_id)
            lines.append(f"    - {food.name_ru}: {item.quantity:g} x {measure.name_ru}")
    return "\n".join(lines)


async def main(meal: MealType, kcal: float) -> int:
    """Run one raw request, validate it, then run the full meal builder."""
    settings = get_settings()
    catalog, _ = catalog_from_rows(load_foods(), load_measures())
    llm = build_llm(settings, catalog)
    if isinstance(llm, FakeLLM):
        print("LLM_API_KEY and LLM_BASE_URL are not both set in .env: nothing to try.")
        return 2

    allowed = tuple(f.id for f in catalog.foods if f.state is not FoodState.RAW)
    print(f"model: {settings.llm_model}  base_url: {settings.llm_base_url}\n")

    print("== 1. Raw answer of the model ==")
    try:
        raw = await llm.generate(DishRequest(meal, kcal, allowed))
    except LLMError as error:
        print(f"LLM error: {error}")
        return 1
    print(raw[:RAW_PREVIEW_CHARS] + (" ..." if len(raw) > RAW_PREVIEW_CHARS else ""))

    print("\n== 2. Validation of that answer ==")
    try:
        dishes = parse_dishes(raw, catalog, allowed, settings.menu)
        print(f"OK: {len(dishes)} valid dish(es): {[d.name for d in dishes]}")
    except InvalidLLMResponseError as error:
        print("REJECTED, the problems below would be sent back to the model:")
        for problem in error.problems:
            print(f"  - {problem}")

    print("\n== 3. Full meal builder (retries, portion fitting, fallback) ==")
    result = await build_meal(llm, catalog, meal, Nutrients(kcal, 0, 0, 0), allowed, settings.menu)
    print(describe(result, catalog))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meal", nargs="?", default="lunch", choices=[m.value for m in MealType])
    parser.add_argument("kcal", nargs="?", type=float, default=600.0)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(MealType(args.meal), args.kcal)))
