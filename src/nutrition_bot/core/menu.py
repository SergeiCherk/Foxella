"""Menu assembly: validation of LLM output, portion fitting, retries and fallback dishes.

Iron rule 1: the language model only suggests dishes and writes recipe texts. Every number is
computed here from the food catalog, and every answer of the model is validated before use.
"""

import asyncio
import json
import logging
import math
import re
import time
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from nutrition_bot.config import MenuConfig
from nutrition_bot.core.errors import (
    InvalidLLMResponseError,
    InvalidMenuRequestError,
    LLMError,
    MenuUnavailableError,
    UnknownFoodError,
    UnknownMeasureError,
)
from nutrition_bot.core.measures import Catalog, step_for
from nutrition_bot.core.models import (
    DailyNorm,
    Dish,
    DishItem,
    Food,
    FoodState,
    Meal,
    MealType,
    Measure,
    Nutrients,
)
from nutrition_bot.core.nutrition import (
    dish_nutrients,
    item_nutrients,
    meal_nutrients,
    sum_nutrients,
)
from nutrition_bot.core.slip import apply_adjustment

logger = logging.getLogger(__name__)

# asyncio fires timers up to one clock tick early (15.6 ms on Windows, about 1 ns on Linux), so a
# call cancelled "at" the deadline can leave a tiny positive remainder. Less than a tick left
# counts as the deadline reached: otherwise a call that is cancelled at once would be started.
DEADLINE_SLACK_S = time.get_clock_info("monotonic").resolution

MAX_PROBLEMS = 8  # more feedback would only confuse the model
CALORIE_WORDS = re.compile(r"ккал|калор|kcal", re.IGNORECASE)


class MealSource(StrEnum):
    """Where the dishes of a meal came from."""

    LLM = "llm"
    FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class DishRequest:
    """What the model is asked for. ``allowed_food_ids``: cooked or ready foods it may use."""

    meal_type: MealType
    target_kcal: float
    allowed_food_ids: tuple[int, ...]
    avoid_dish_names: tuple[str, ...] = ()
    feedback: tuple[str, ...] = ()  # problems found in the previous answer


@dataclass(frozen=True, slots=True)
class MealResult:
    """A finished meal with its computed nutrients and how it came about."""

    meal: Meal
    nutrients: Nutrients
    source: MealSource
    attempts: int  # number of LLM calls made
    problems: tuple[str, ...]  # why the last attempt failed (empty if the LLM succeeded)
    ignored_availability: bool = False  # a fallback dish used foods the user did not list


class DishGenerator(Protocol):
    """Anything that can answer a ``DishRequest`` with raw JSON text (real LLM or a test stub)."""

    async def generate(self, request: DishRequest) -> str:
        """Return the model's raw answer. Raise ``LLMError`` if it cannot be obtained."""
        ...


# --------------------------------------------------------------- targets


def meal_targets(
    day: Nutrients, meal_types: Sequence[MealType], cfg: MenuConfig
) -> dict[MealType, Nutrients]:
    """Split the daily target between the meals by ``cfg.meal_shares`` (renormalised)."""
    if not meal_types:
        raise InvalidMenuRequestError("at least one meal is required")
    if len(set(meal_types)) != len(meal_types):
        raise InvalidMenuRequestError("meal types must not repeat")
    shares = {}
    for meal_type in meal_types:
        share = cfg.meal_shares.get(meal_type.value)
        if share is None or share <= 0:
            raise InvalidMenuRequestError(f"no share configured for {meal_type.value}")
        shares[meal_type] = share
    total = sum(shares.values())
    return {
        mt: Nutrients(
            kcal=day.kcal * s / total,
            protein_g=day.protein_g * s / total,
            fat_g=day.fat_g * s / total,
            carb_g=day.carb_g * s / total,
            fiber_g=day.fiber_g * s / total,
        )
        for mt, s in shares.items()
    }


# -------------------------------------------------------------- parsing


def _extract_json(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise InvalidLLMResponseError(["response is not valid JSON"])


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _parse_item(
    label: str, entry: object, catalog: Catalog, allowed: set[int], cfg: MenuConfig
) -> tuple[DishItem | None, list[str]]:
    if not isinstance(entry, dict):
        return None, [f"{label}: must be an object"]
    food_id = _as_int(entry.get("food_id"))
    measure_id = _as_int(entry.get("measure_id"))
    quantity = _as_number(entry.get("quantity"))
    problems: list[str] = []
    if food_id is None:
        problems.append(f"{label}: food_id must be an integer")
    if measure_id is None:
        problems.append(f"{label}: measure_id must be an integer")
    if quantity is None or not 0 < quantity <= cfg.max_quantity:
        problems.append(
            f"{label}: quantity must be a number above 0 and at most {cfg.max_quantity:g}"
        )
    if problems or food_id is None or measure_id is None or quantity is None:
        return None, problems
    try:
        catalog.get_measure(food_id, measure_id)
    except UnknownFoodError:
        return None, [f"{label}: unknown food_id {food_id}"]
    except UnknownMeasureError:
        return None, [f"{label}: measure_id {measure_id} does not belong to food_id {food_id}"]
    if food_id not in allowed:
        return None, [f"{label}: food_id {food_id} is not in the allowed list"]
    return DishItem(food_id, measure_id, quantity), []


def _parse_dish(
    number: int, entry: object, catalog: Catalog, allowed: set[int], cfg: MenuConfig
) -> tuple[Dish | None, list[str]]:
    label = f"dish {number}"
    if not isinstance(entry, dict):
        return None, [f"{label}: must be an object"]
    problems: list[str] = []

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > cfg.max_name_length:
        problems.append(
            f"{label}: name must be a non-empty string up to {cfg.max_name_length} chars"
        )
    recipe = entry.get("recipe")
    if not isinstance(recipe, str) or not recipe.strip() or len(recipe) > cfg.max_recipe_length:
        problems.append(
            f"{label}: recipe must be a non-empty string up to {cfg.max_recipe_length} chars"
        )
    elif CALORIE_WORDS.search(recipe):
        problems.append(f"{label}: recipe must not mention calories, the program computes them")

    raw_items = entry.get("items")
    items: list[DishItem] = []
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= cfg.max_items_per_dish:
        problems.append(f"{label}: items must be a list of 1 to {cfg.max_items_per_dish} entries")
    else:
        for n, raw_item in enumerate(raw_items, start=1):
            item, item_problems = _parse_item(f"{label} item {n}", raw_item, catalog, allowed, cfg)
            problems += item_problems
            if item is not None:
                items.append(item)
        food_ids = [i.food_id for i in items]
        if len(set(food_ids)) != len(food_ids):
            problems.append(f"{label}: the same food appears twice, merge the quantities")

    if problems or not isinstance(name, str) or not isinstance(recipe, str):
        return None, problems
    return Dish(name.strip(), tuple(items), recipe.strip()), []


def parse_dishes(
    raw: str, catalog: Catalog, allowed_food_ids: Sequence[int], cfg: MenuConfig
) -> list[Dish]:
    """Turn the model's raw answer into validated dishes.

    Expected shape: ``{"dishes": [{"name", "recipe", "items": [{"food_id", "measure_id",
    "quantity"}]}]}``. Raises ``InvalidLLMResponseError`` listing *all* problems found, so the
    model can fix them in one retry.
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise InvalidLLMResponseError(["the top level must be a JSON object with a 'dishes' list"])
    entries = data.get("dishes")
    if not isinstance(entries, list) or not entries:
        raise InvalidLLMResponseError(["'dishes' must be a non-empty list"])

    problems: list[str] = []
    if len(entries) > cfg.max_dishes_per_meal:
        problems.append(f"at most {cfg.max_dishes_per_meal} dishes are allowed")
    allowed = set(allowed_food_ids)
    dishes: list[Dish] = []
    seen_names: set[str] = set()
    for number, entry in enumerate(entries, start=1):
        dish, dish_problems = _parse_dish(number, entry, catalog, allowed, cfg)
        problems += dish_problems
        if dish is None:
            continue
        if dish.name.casefold() in seen_names:
            problems.append(f"dish {number}: duplicate dish name")
        seen_names.add(dish.name.casefold())
        dishes.append(dish)
    if problems:
        raise InvalidLLMResponseError(problems[:MAX_PROBLEMS])
    return dishes


# ------------------------------------------------------ portion fitting


def within_tolerance(kcal: float, target_kcal: float, tolerance: float) -> bool:
    """Is ``kcal`` within +-``tolerance`` (a share) of the target? The boundary is inclusive."""
    return abs(kcal - target_kcal) <= tolerance * target_kcal + 1e-9


def _is_whole(catalog: Catalog, item: DishItem, whole_measures: Collection[str]) -> bool:
    return catalog.get_measure(item.food_id, item.measure_id).name_ru in whole_measures


def _scale_dish(
    catalog: Catalog,
    dish: Dish,
    scale: float,
    step: float,
    whole_measures: Collection[str],
    free_scale: float | None = None,
    *,
    coarse_step: float | None = None,
    fine_measures: Collection[str] = (),
) -> Dish:
    """Scale a dish and round to household steps; whole pieces (eggs, ...) to whole numbers.

    ``free_scale``, if given, replaces ``scale`` for everything that is not a whole piece.
    """
    items = []
    for i in dish.items:
        measure = catalog.get_measure(i.food_id, i.measure_id)
        s = step_for(
            measure, step, whole_measures, coarse_step=coarse_step, fine_measures=fine_measures
        )
        is_whole = measure.name_ru in whole_measures
        factor = free_scale if free_scale is not None and not is_whole else scale
        items.append(
            DishItem(i.food_id, i.measure_id, max(s, math.floor(i.quantity * factor / s + 0.5) * s))
        )
    return Dish(dish.name, tuple(items), dish.recipe_text)


def _free_scale(
    catalog: Catalog,
    dishes: Sequence[Dish],
    scale: float,
    target_kcal: float,
    whole_measures: Collection[str],
) -> float | None:
    """The factor for the non-whole items that fills the kcal the whole pieces leave over.

    Whole pieces cannot flex (an egg is 1 or 2, never 1.3), so after they are rounded the rest
    of the meal has to make up the difference. ``None`` if there is nothing to flex or nothing
    left to fill.
    """
    fixed = 0.0
    free = 0.0
    for dish in dishes:
        for item in dish.items:
            if _is_whole(catalog, item, whole_measures):
                rounded = DishItem(
                    item.food_id, item.measure_id, max(1.0, math.floor(item.quantity * scale + 0.5))
                )
                fixed += item_nutrients(catalog, rounded).kcal
            else:
                free += item_nutrients(catalog, item).kcal
    if free <= 0 or target_kcal - fixed <= 0:
        return None
    return (target_kcal - fixed) / free


def fit_portions(
    catalog: Catalog,
    dishes: Sequence[Dish],
    target_kcal: float,
    cfg: MenuConfig,
    *,
    wide: bool = False,
) -> tuple[list[Dish] | None, str]:
    """Scale all quantities by one factor so that the meal hits the kcal target.

    Quantities are rounded to household steps: halves first, then quarters for glasses and
    spoons, and quarters for any measure only as a last resort. Whole pieces such as eggs and
    tomatoes always go to whole numbers (at least 1). Because whole pieces cannot flex, the other
    ingredients are re-scaled to fill the rest of the kcal when the first attempt misses the
    target. Returns ``(dishes, "")`` or ``(None, reason)``. ``wide`` allows larger scale factors
    (for our own fallback dishes).
    """
    total = sum_nutrients(dish_nutrients(catalog, d) for d in dishes).kcal
    if total <= 0:
        return None, "the meal has no calories"
    low, high = (
        (cfg.fallback_min_scale, cfg.fallback_max_scale) if wide else (cfg.min_scale, cfg.max_scale)
    )
    scale = target_kcal / total
    if not low <= scale <= high:
        return None, (
            f"the meal totals {total:.0f} kcal but about {target_kcal:.0f} kcal is needed; "
            "adjust the dishes and portions"
        )
    free_scale = _free_scale(catalog, dishes, scale, target_kcal, cfg.whole_measures)
    coarse = cfg.quantity_steps[0]
    # Passes, from the most natural wording to the least: halves; quarters for glasses and
    # spoons only; and only if nothing else fits, quarters for every measure.
    passes = [(step, True) for step in cfg.quantity_steps]
    if cfg.quantity_steps[-1] < coarse:
        passes.append((cfg.quantity_steps[-1], False))
    for step, keep_coarse in passes:
        attempts: list[float | None] = [None]
        if free_scale is not None and low <= free_scale <= high:
            attempts.append(free_scale)
        for free in attempts:
            fitted = [
                _scale_dish(
                    catalog,
                    d,
                    scale,
                    step,
                    cfg.whole_measures,
                    free,
                    coarse_step=coarse if keep_coarse else None,
                    fine_measures=cfg.fine_measures,
                )
                for d in dishes
            ]
            kcal = sum_nutrients(dish_nutrients(catalog, d) for d in fitted).kcal
            if within_tolerance(kcal, target_kcal, cfg.meal_tolerance):
                return fitted, ""
    return None, "portions cannot be rounded to household measures close enough to the target"


# ------------------------------------------------------- fallback dishes


@dataclass(frozen=True, slots=True)
class _Template:
    name: str
    recipe: str
    meal_types: tuple[MealType, ...]
    # (food code or interchangeable codes "a|b|c", measure name, quantity). With several
    # codes the first one the user has is used, else the first one that exists.
    items: tuple[tuple[str, str, float], ...]


B, L, D, S = MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK

FALLBACK_TEMPLATES: tuple[_Template, ...] = (
    _Template(
        "Овсянка с бананом и орехами",
        "Сварите овсяные хлопья на воде до мягкости. Нарежьте банан кружочками и выложите "
        "сверху вместе с грецкими орехами.",
        (B,),
        (
            ("oatmeal_cooked", "тарелка", 1),
            ("banana", "банан", 1),
            ("walnuts|almonds|hazelnuts|peanuts|cashew", "горсть", 0.5),
        ),
    ),
    _Template(
        "Творог с яблоком и мёдом",
        "Выложите творог в тарелку, добавьте нарезанное кубиками яблоко и полейте мёдом.",
        (B, S),
        (
            ("cottage_5|cottage_0|cottage_9", "пачка", 1),
            ("apple", "яблоко", 1),
            ("honey", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Омлет с помидором и ржаным хлебом",
        "Взбейте яйца вилкой с щепоткой соли. Обжарьте на сковороде с маслом, добавив "
        "нарезанный помидор. Подавайте с ломтиком хлеба.",
        (B, D),
        (
            ("egg_boiled", "яйцо", 2),
            ("tomato", "помидор", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
            ("bread_rye|bread_wholegrain|bread_white", "ломтик", 1),
        ),
    ),
    _Template(
        "Йогурт с бананом и миндалём",
        "Выложите йогурт в стакан или миску, добавьте банан кружочками и миндаль.",
        (B, S),
        (
            ("yogurt_natural", "стакан", 1),
            ("banana", "банан", 1),
            ("almonds|walnuts|hazelnuts|peanuts|cashew", "горсть", 0.5),
        ),
    ),
    _Template(
        "Курица с гречкой и огурцом",
        "Запеките или отварите куриную грудку и нарежьте ломтиками. Подайте с горячей гречкой "
        "и свежим огурцом, полив гречку маслом.",
        (L, D),
        (
            ("chicken_breast_cooked", "грудка", 1),
            ("buckwheat_cooked", "половник", 2),
            ("cucumber", "огурец", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Треска с рисом и брокколи",
        "Запеките филе трески 15–20 минут. Отварите рис и брокколи. Подавайте вместе, "
        "добавив немного оливкового масла.",
        (L, D),
        (
            ("cod_cooked|pollock_cooked", "филе", 1),
            ("rice_white_cooked|rice_brown_cooked", "половник", 2),
            ("broccoli", "стакан", 1),
            ("olive_oil|sunflower_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Индейка с булгуром и болгарским перцем",
        "Обжарьте или запеките грудку индейки. Отварите булгур. Нарежьте перец полосками и "
        "обжарьте минуту на масле. Подавайте всё вместе.",
        (L, D),
        (
            ("turkey_breast_cooked", "кусок", 1),
            ("bulgur_cooked", "половник", 2),
            ("bell_pepper", "перец", 1),
            ("olive_oil|sunflower_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Чечевица с морковью и яйцом",
        "Отварите чечевицу до мягкости. Обжарьте тёртую морковь на масле, смешайте с чечевицей. "
        "Подавайте с варёным яйцом.",
        (L, D),
        (
            ("lentils_cooked", "стакан", 1),
            ("carrot", "морковь", 1),
            ("egg_boiled", "яйцо", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Лосось с картофелем и шпинатом",
        "Запеките стейк лосося 15 минут. Отварите картофель. Подавайте со свежим шпинатом.",
        (L, D),
        (
            ("salmon_cooked", "стейк", 1),
            ("potato_boiled", "картофелина", 2),
            ("spinach", "горсть", 1),
        ),
    ),
    _Template(
        "Паста с курицей и помидором",
        "Отварите макароны. Нарежьте готовую куриную грудку и помидор, смешайте с пастой и "
        "заправьте оливковым маслом.",
        (L, D),
        (
            ("pasta_cooked", "стакан", 1),
            ("chicken_breast_cooked", "грудка", 0.5),
            ("tomato", "помидор", 1),
            ("olive_oil|sunflower_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Яблоко с миндалём",
        "Нарежьте яблоко дольками и подайте с горстью миндаля.",
        (S,),
        (("apple", "яблоко", 1), ("almonds|walnuts|hazelnuts|peanuts|cashew", "горсть", 0.5)),
    ),
    _Template(
        "Кефир с бананом",
        "Налейте кефир в стакан, подайте с бананом.",
        (S,),
        (("kefir_1|kefir_2_5", "стакан", 1), ("banana", "банан", 1)),
    ),
    _Template(
        "Творог с мандаринами",
        "Выложите творог в миску и добавьте очищенные дольки мандарина.",
        (S,),
        (("cottage_0|cottage_5|cottage_9", "пачка", 0.5), ("mandarin", "мандарин", 2)),
    ),
    _Template(
        "Хлебец с сыром и огурцом",
        "Положите ломтик сыра и несколько кружочков огурца на хлеб.",
        (S,),
        (
            ("bread_wholegrain|bread_rye|bread_white", "ломтик", 2),
            ("cheese_hard", "ломтик", 1),
            ("cucumber", "огурец", 1),
        ),
    ),
    _Template(
        "Омлет с помидором и огурцом",
        "Взбейте яйца вилкой с щепоткой соли. Обжарьте на сковороде с маслом вместе с нарезанным "
        "помидором. Огурец нарежьте отдельно и подайте рядом.",
        (B, D),
        (
            ("egg_boiled", "яйцо", 2),
            ("tomato", "помидор", 1),
            ("cucumber", "огурец", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Гречка с яйцом и помидором",
        "Отварите гречку и яйца вкрутую. Нарежьте помидор. Заправьте гречку маслом и подайте "
        "с яйцами и помидором.",
        (L, D),
        (
            ("buckwheat_cooked", "половник", 2),
            ("egg_boiled", "яйцо", 2),
            ("tomato", "помидор", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Творог с огурцом и зеленью",
        "Смешайте творог с нарезанным огурцом и рубленой зеленью, добавьте щепотку соли.",
        (B, D, S),
        (
            ("cottage_5|cottage_0|cottage_9", "пачка", 1),
            ("cucumber", "огурец", 1),
            ("greens_herbs", "пучок", 1),
        ),
    ),
    _Template(
        "Овсянка с яблоком и мёдом",
        "Сварите овсяные хлопья на воде до мягкости. Добавьте яблоко кубиками и полейте мёдом.",
        (B,),
        (("oatmeal_cooked", "тарелка", 1), ("apple", "яблоко", 1), ("honey", "чайная ложка", 1)),
    ),
    _Template(
        "Говядина с картофелем и капустой",
        "Отварите или потушите говядину и нарежьте ломтиками. Отварите картофель. Подайте со "
        "свежей капустой, заправленной маслом.",
        (L, D),
        (
            ("beef_lean_cooked", "кусок", 1),
            ("potato_boiled", "картофелина", 2),
            ("cabbage_white", "стакан", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Рыба с картофелем и огурцом",
        "Запеките филе рыбы 15–20 минут. Отварите картофель. Подайте с нарезанным огурцом, "
        "добавив немного масла.",
        (L, D),
        (
            ("pollock_cooked|cod_cooked", "филе", 1),
            ("potato_boiled", "картофелина", 2),
            ("cucumber", "огурец", 1),
            ("sunflower_oil|olive_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Рис с курицей и брокколи",
        "Отварите рис и брокколи. Запеките куриную грудку и нарежьте. Соедините всё на тарелке "
        "и добавьте масло.",
        (L, D),
        (
            ("rice_white_cooked|rice_brown_cooked", "половник", 2),
            ("chicken_breast_cooked", "грудка", 1),
            ("broccoli", "стакан", 1),
            ("olive_oil|sunflower_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Макароны с индейкой и перцем",
        "Отварите макароны. Нарежьте перец полосками и обжарьте минуту на масле. Добавьте "
        "готовую индейку и смешайте с макаронами.",
        (L, D),
        (
            ("pasta_cooked", "стакан", 1),
            ("turkey_breast_cooked", "кусок", 1),
            ("bell_pepper", "перец", 1),
            ("olive_oil|sunflower_oil", "чайная ложка", 1),
        ),
    ),
    _Template(
        "Кефир с яблоком",
        "Налейте кефир в стакан, яблоко нарежьте дольками и подайте рядом.",
        (S,),
        (("kefir_1|kefir_2_5", "стакан", 1), ("apple", "яблоко", 1)),
    ),
    _Template(
        "Банан и горсть орехов",
        "Подайте банан с горстью орехов.",
        (S,),
        (
            ("banana", "банан", 1),
            ("almonds|walnuts|hazelnuts|peanuts|cashew", "горсть", 0.5),
        ),
    ),
    _Template(
        "Творог с огурцом",
        "Выложите творог в миску и подайте с нарезанным огурцом.",
        (S, B),
        (("cottage_5|cottage_0|cottage_9", "пачка", 1), ("cucumber", "огурец", 1)),
    ),
    _Template(
        "Яйца с помидором",
        "Очистите яйца, сваренные вкрутую, и нарежьте. Подайте с нарезанным помидором.",
        (S, B),
        (("egg_boiled", "яйцо", 2), ("tomato", "помидор", 1)),
    ),
)


def _resolve(
    template: _Template, catalog: Catalog, allowed: Collection[int] | None = None
) -> Dish | None:
    """Turn a template into a dish. Of several interchangeable foods, the user's one is chosen."""
    by_code = {f.code: f for f in catalog.foods}
    items: list[DishItem] = []
    for codes, measure_name, quantity in template.items:
        options: list[tuple[Food, Measure]] = []
        for code in codes.split("|"):
            food = by_code.get(code)
            measure = (
                next((m for m in catalog.measures_for(food.id) if m.name_ru == measure_name), None)
                if food
                else None
            )
            if food is not None and measure is not None:
                options.append((food, measure))
        if not options:
            logger.warning(
                "fallback template %r skipped: %s/%s not in catalog",
                template.name,
                codes,
                measure_name,
            )
            return None
        food, measure = next(
            ((f, m) for f, m in options if allowed is not None and f.id in allowed), options[0]
        )
        items.append(DishItem(food.id, measure.id, quantity))
    return Dish(template.name, tuple(items), template.recipe)


def fallback_dishes(
    catalog: Catalog,
    meal_type: MealType,
    target_kcal: float,
    allowed_food_ids: Sequence[int],
    cfg: MenuConfig,
    avoid_names: Sequence[str] = (),
) -> tuple[list[Dish], bool]:
    """Pick one of our own dishes for the meal and fit it to the target.

    Dishes made only of foods the user has come first; if none fits, dishes with other foods
    are used and the second return value is ``True``. Dishes already used are chosen last.
    Raises ``MenuUnavailableError`` if nothing can be fitted.
    """
    avoid = {n.casefold() for n in avoid_names}
    allowed = set(allowed_food_ids)
    resolved = [
        dish
        for template in FALLBACK_TEMPLATES
        if meal_type in template.meal_types
        and (dish := _resolve(template, catalog, allowed)) is not None
    ]
    for ignore_availability in (False, True):
        pool = [
            d for d in resolved if ignore_availability or all(i.food_id in allowed for i in d.items)
        ]
        pool.sort(
            key=lambda d: (
                d.name.casefold() in avoid,
                abs(dish_nutrients(catalog, d).kcal - target_kcal),
            )
        )
        for dish in pool:
            fitted, _ = fit_portions(catalog, [dish], target_kcal, cfg, wide=True)
            if fitted is not None:
                return fitted, ignore_availability
    raise MenuUnavailableError(meal_type.value)


# ----------------------------------------------------------- orchestration


async def build_meal(
    generator: DishGenerator,
    catalog: Catalog,
    meal_type: MealType,
    target: Nutrients,
    allowed_food_ids: Sequence[int],
    cfg: MenuConfig,
    avoid_names: Sequence[str] = (),
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> MealResult:
    """Build one meal: ask the model (with feedback and retries), else use a fallback dish.

    ``deadline`` is a ``clock()`` timestamp. A call that is still running at the deadline is
    cancelled and no new call is started: the rest of the meal comes from the fallback dishes.
    """
    allowed = tuple(allowed_food_ids)
    avoid = tuple(avoid_names)
    avoid_folded = {n.casefold() for n in avoid}
    feedback: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    attempts = 0

    for _ in range(1 + cfg.max_llm_retries):
        remaining = None if deadline is None else deadline - clock()
        if remaining is not None and remaining <= DEADLINE_SLACK_S:
            problems = ("the time limit was reached",)
            logger.warning("time limit reached before attempt %d", attempts + 1)
            break
        attempts += 1
        request = DishRequest(meal_type, target.kcal, allowed, avoid, feedback)
        try:
            raw = await asyncio.wait_for(generator.generate(request), timeout=remaining)
            dishes = parse_dishes(raw, catalog, allowed, cfg)
            repeated = [d.name for d in dishes if d.name.casefold() in avoid_folded]
            if repeated:
                raise InvalidLLMResponseError(
                    [f"dish name was already used: {n}" for n in repeated]
                )
            fitted, reason = fit_portions(catalog, dishes, target.kcal, cfg)
            if fitted is None:
                raise InvalidLLMResponseError([reason])
        except InvalidLLMResponseError as error:
            problems = feedback = tuple(error.problems)
            logger.warning(
                "LLM answer rejected (attempt %d): %d problem(s)", attempts, len(problems)
            )
            continue
        except LLMError as error:
            problems = ("the language model was unavailable",)
            logger.warning("LLM call failed (attempt %d): %s", attempts, error)
            continue
        except TimeoutError:
            problems = ("the time limit was reached",)
            logger.warning("LLM call cancelled at the time limit (attempt %d)", attempts)
            break
        meal = Meal(meal_type, tuple(fitted))
        return MealResult(meal, meal_nutrients(catalog, meal), MealSource.LLM, attempts, ())

    dishes_fb, ignored = fallback_dishes(catalog, meal_type, target.kcal, allowed, cfg, avoid)
    meal = Meal(meal_type, tuple(dishes_fb))
    logger.info("fallback dish used for %s after %d attempt(s)", meal_type.value, attempts)
    return MealResult(
        meal, meal_nutrients(catalog, meal), MealSource.FALLBACK, attempts, problems, ignored
    )


async def build_day(
    generator: DishGenerator,
    catalog: Catalog,
    day_target: Nutrients,
    meal_types: Sequence[MealType],
    allowed_food_ids: Sequence[int],
    cfg: MenuConfig,
    avoid_names: Sequence[str] = (),
    deadline: float | None = None,
) -> list[MealResult]:
    """Build all meals of a day. Dish names already used are not repeated within the day."""
    targets = meal_targets(day_target, meal_types, cfg)
    used = list(avoid_names)
    results: list[MealResult] = []
    for meal_type in meal_types:
        result = await build_meal(
            generator,
            catalog,
            meal_type,
            targets[meal_type],
            allowed_food_ids,
            cfg,
            tuple(used),
            deadline,
        )
        used += [d.name for d in result.meal.dishes]
        results.append(result)
    return results


# ------------------------------------------------------------- availability


def staple_food_ids(catalog: Catalog, codes: Iterable[str]) -> tuple[int, ...]:
    """Ids of the staple foods (oil, sugar...) by code; codes not in the catalog are skipped."""
    wanted = set(codes)
    found = {f.code: f.id for f in catalog.foods if f.code in wanted}
    missing = wanted - found.keys()
    if missing:
        logger.warning("staple foods not in the catalog: %s", sorted(missing))
    return tuple(sorted(found.values()))


def menu_food_ids(
    catalog: Catalog,
    food_ids: Iterable[int] | None = None,
    always_food_ids: Iterable[int] = (),
) -> tuple[int, ...]:
    """Foods a menu may use, given the products the user has.

    A dish is made of cooked or ready foods, so a raw product the user listed ("rice") is
    replaced by its cooked versions ("boiled rice"). ``None`` means "any product": every
    cooked or ready food. ``always_food_ids`` (staples such as oil) are added to a given list,
    so a person who did not mention oil still gets dishes with oil. Raises ``UnknownFoodError``
    for an unknown id.
    """
    if food_ids is None:
        return tuple(sorted(f.id for f in catalog.foods if f.state is not FoodState.RAW))
    allowed: set[int] = set()
    for food_id in food_ids:
        food = catalog.get_food(food_id)
        if food.state is FoodState.RAW:
            allowed.update(
                f.id
                for f in catalog.foods
                if f.state is FoodState.COOKED and f.raw_food_id == food.id
            )
        else:
            allowed.add(food.id)
    for food_id in always_food_ids:
        allowed.add(catalog.get_food(food_id).id)
    return tuple(sorted(allowed))


async def build_menu(
    generator: DishGenerator,
    catalog: Catalog,
    norm: DailyNorm,
    days: int,
    allowed_food_ids: Sequence[int],
    cfg: MenuConfig,
    adjustments: Sequence[float] = (),
) -> list[list[MealResult]]:
    """Build a menu for 1..``cfg.max_days`` days.

    ``adjustments`` are kcal changes for the first days (after eating off-plan); a day is never
    planned below the kcal floor. Dishes are not repeated within the whole menu.
    """
    if not 1 <= days <= cfg.max_days:
        raise InvalidMenuRequestError(f"days must be between 1 and {cfg.max_days}")
    meal_types = [MealType(value) for value in cfg.meal_order]
    deadline = time.monotonic() + cfg.build_timeout_s
    used: list[str] = []
    menu: list[list[MealResult]] = []
    for day in range(days):
        target = apply_adjustment(norm, adjustments[day]) if day < len(adjustments) else norm.target
        results = await build_day(
            generator, catalog, target, meal_types, allowed_food_ids, cfg, tuple(used), deadline
        )
        used += [dish.name for result in results for dish in result.meal.dishes]
        menu.append(results)
    return menu
