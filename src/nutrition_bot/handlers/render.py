"""Turning core results into Russian messages. Pure functions, easy to test.

Quantities are shown in household measures only ("2 половника", "полстакана"); grams never
appear. Nutrients shown to the user are the ones computed by code.
"""

from collections.abc import Iterable, Sequence
from functools import lru_cache
from html import escape

import pymorphy3
from pymorphy3.analyzer import Parse

from nutrition_bot import texts
from nutrition_bot.core.balance import BalanceHint
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import DishItem, FoodCategory, Meal, Nutrients
from nutrition_bot.core.nutrition import day_nutrients, dish_nutrients, meal_nutrients
from nutrition_bot.core.shopping import ShoppingItem

TELEGRAM_LIMIT = 4000  # a message may hold 4096 characters; keep a margin
_FEW = {2, 3, 4}
MAX_RECIPE_CHARS = 700  # a recipe longer than this is cut, so one meal always fits a message


@lru_cache(maxsize=1)
def _morph() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


def format_number(value: float) -> str:
    """Whole numbers as is, anything else with one decimal comma (quarters are words, see
    ``measure_phrase``)."""
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}".replace(".", ",")


def _pick(word: str, pos: str) -> Parse:
    """The parse of ``word`` as a dictionary form of ``pos`` ("банка" is a jar, not "of a bank")."""
    parses = [p for p in _morph().parse(word) if pos in p.tag] or _morph().parse(word)
    return next(
        (p for p in parses if p.normal_form.replace("ё", "е") == word.replace("ё", "е")), parses[0]
    )


def _form(parse: Parse, grammemes: set[str]) -> str:
    inflected = parse.inflect(grammemes)
    return str(inflected.word if inflected is not None else parse.word)


def _half(genitive: str, one_word: bool) -> str:
    """ "стакана" -> "полстакана", "яблока" -> "пол-яблока"; several words -> "половина ..."."""
    if not one_word or genitive.startswith("пол"):
        return f"половина {genitive}"
    hyphen = "-" if genitive[0] in "аеёиоуыэюял" else ""
    return f"пол{hyphen}{genitive}"


def measure_phrase(name: str, quantity: float) -> str:
    """ "половник", 2 -> "2 половника"; "столовая ложка", 5 -> "5 столовых ложек".

    The noun agrees with the number as in Russian speech; adjectives before it follow. Parts are
    words, never fraction signs: "полстакана", "четверть пачки", "полтора половника",
    "2 с половиной стакана", "1 и три четверти чайной ложки".
    """
    words = name.split()
    noun = _pick(words[-1], "NOUN")
    adjectives = [_pick(w, "ADJF") for w in words[:-1]]
    count = int(quantity)
    rest = round(quantity - count, 2)
    feminine = "femn" in noun.tag

    if rest:
        gent = {"gent", "sing"}
        genitive = " ".join(
            [_form(a, gent | ({"femn"} if feminine else set())) for a in adjectives]
            + [_form(noun, gent)]
        )
        if count == 0 and rest == 0.5:
            return _half(genitive, not adjectives)
        if count == 0 and rest == 0.25:
            return f"четверть {genitive}"
        if count == 0 and rest == 0.75:
            return f"три четверти {genitive}"
        if count == 1 and rest == 0.5:
            # "полтора стакана", but "полторы столовых ложки": the adjective goes plural
            parts = [_form(a, {"gent", "plur"}) for a in adjectives] + [_form(noun, gent)]
            return f"{'полторы' if feminine else 'полтора'} {' '.join(parts)}"
        if rest == 0.75:
            return f"{count} и три четверти {genitive}"
        if rest in (0.25, 0.5):
            joined = "с четвертью" if rest == 0.25 else "с половиной"
            number, noun_part = measure_phrase(name, count).split(" ", 1)
            return f"{number} {joined} {noun_part}"
        return f"{format_number(quantity)} {genitive}"

    number = format_number(quantity)
    if count % 100 not in range(11, 15) and count % 10 == 1:
        noun_form, adj_form = {"nomn", "sing"}, {"nomn", "sing"} | ({"femn"} if feminine else set())
    elif count % 100 not in range(11, 15) and count % 10 in _FEW:
        noun_form = {"gent", "sing"}
        adj_form = {"nomn", "plur"} if feminine else {"gent", "plur"}
    else:
        noun_form, adj_form = {"gent", "plur"}, {"gent", "plur"}

    parts = [_form(a, adj_form) for a in adjectives] + [_form(noun, noun_form)]
    return f"{number} {' '.join(parts)}"


def plural(count: int, forms: tuple[str, str, str]) -> str:
    """ "32", ("год", "года", "лет") -> "32 года"."""
    if count % 100 in range(11, 15):
        word = forms[2]
    elif count % 10 == 1:
        word = forms[0]
    elif count % 10 in _FEW:
        word = forms[1]
    else:
        word = forms[2]
    return f"{count} {word}"


def _kcal_line(n: Nutrients) -> tuple[int, int, int, int]:
    return round(n.kcal), round(n.protein_g), round(n.fat_g), round(n.carb_g)


def render_item(catalog: Catalog, item: DishItem) -> str:
    """One ingredient: ``• Рис белый (варёный) — 2 половника``."""
    food = catalog.get_food(item.food_id)
    measure = catalog.get_measure(item.food_id, item.measure_id)
    return f"• {food.name_ru} — {measure_phrase(measure.name_ru, item.quantity)}"


def html_text(value: str) -> str:
    """Escape text for Telegram HTML (names and recipes may come from the language model)."""
    return escape(value, quote=False)


def shorten(text: str, limit: int = MAX_RECIPE_CHARS) -> str:
    """Cut ``text`` at a word boundary and add an ellipsis if it is longer than ``limit``."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def render_item_html(catalog: Catalog, item: DishItem) -> str:
    """One ingredient: ``🌾 Рис белый (варёный) — <b>2 половника</b>``."""
    food = catalog.get_food(item.food_id)
    measure = catalog.get_measure(item.food_id, item.measure_id)
    icon = texts.CATEGORY_ICONS.get(food.category, "•")
    amount = measure_phrase(measure.name_ru, item.quantity)
    return f"{icon} {html_text(food.name_ru)} — <b>{html_text(amount)}</b>"


def render_meal(catalog: Catalog, meal: Meal) -> str:
    """One meal as a Telegram HTML message: title, dishes with ingredients, folded recipes."""
    kcal, protein, fat, carb = _kcal_line(meal_nutrients(catalog, meal))
    lines = [
        texts.MEAL_LINE.format(
            icon=texts.MEAL_ICONS[meal.meal_type],
            title=texts.MEAL_TITLES[meal.meal_type],
            kcal=kcal,
            protein=protein,
            fat=fat,
            carb=carb,
        )
    ]
    several = len(meal.dishes) > 1
    for dish in meal.dishes:
        title = f"<b>{html_text(dish.name)}</b>"
        if several:
            title += texts.DISH_KCAL.format(kcal=round(dish_nutrients(catalog, dish).kcal))
        lines += ["", title]
        lines.extend(render_item_html(catalog, item) for item in dish.items)
        if dish.recipe_text:
            recipe = html_text(shorten(dish.recipe_text))
            lines += ["", f"<blockquote expandable>{texts.RECIPE_LABEL}{recipe}</blockquote>"]
    return "\n".join(lines)


def render_day(catalog: Catalog, number: int, meals: Sequence[Meal]) -> list[str]:
    """Message blocks of one day: the header with day totals, then one block per meal."""
    kcal, protein, fat, carb = _kcal_line(day_nutrients(catalog, meals))
    header = texts.DAY_TITLE.format(n=number, kcal=kcal, protein=protein, fat=fat, carb=carb)
    return [header, *(render_meal(catalog, meal) for meal in meals)]


def render_hints(hints: Iterable[BalanceHint]) -> str:
    """The "what is missing" block (HTML); duplicates once. Empty string if nothing to say."""
    lines: list[str] = []
    for hint in hints:
        meal = texts.MEAL_IN[hint.meal_type] if hint.meal_type else ""
        line = "• " + html_text(texts.HINT_TEXTS[hint.kind].format(meal=meal))
        if line not in lines:
            lines.append(line)
    return f"{texts.HINTS_TITLE}\n" + "\n".join(lines) if lines else ""


def render_shopping(items: Sequence[ShoppingItem], days: int) -> list[str]:
    """Shopping list grouped by category, as HTML message blocks (title first)."""
    blocks = [texts.SHOPPING_HEADER.format(days=texts.DAYS_ACCUSATIVE.get(days, f"{days} дн."))]
    by_category: dict[FoodCategory, list[str]] = {}
    staples: list[str] = []
    for item in items:
        amount = (
            texts.SHOPPING_NO_AMOUNT
            if item.measure is None
            else measure_phrase(item.measure.name_ru, item.quantity)
        )
        line = f"• {html_text(item.food.name_ru)} — <b>{html_text(amount)}</b>"
        if item.is_staple:
            staples.append(line)
        else:
            by_category.setdefault(item.food.category, []).append(line)
    for category, lines in by_category.items():
        icon = texts.CATEGORY_ICONS.get(category, "•")
        title = f"{icon} <b>{texts.SHOPPING_TITLES[category]}</b>"
        blocks.append(f"{title}\n" + "\n".join(lines))
    if staples:
        blocks.append(texts.SHOPPING_STAPLES_TITLE + "\n" + "\n".join(staples))
    return blocks


def pack(blocks: Iterable[str], limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Join blocks into as few messages as possible, none longer than ``limit`` characters."""
    messages: list[str] = []
    current = ""
    for block in blocks:
        block = block[:limit]
        if current and len(current) + 2 + len(block) > limit:
            messages.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        messages.append(current)
    return messages
