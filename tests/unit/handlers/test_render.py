"""Tests for message rendering: declension of measures, blocks, packing."""

import pytest

from nutrition_bot import texts
from nutrition_bot.config import ShoppingConfig
from nutrition_bot.core.balance import BalanceHint, HintKind
from nutrition_bot.core.models import Dish, DishItem, FoodCategory, Meal, MealType
from nutrition_bot.core.shopping import build_shopping_list
from nutrition_bot.db.seed import catalog_from_rows, load_foods, load_measures
from nutrition_bot.handlers.render import (
    MAX_RECIPE_CHARS,
    format_number,
    html_text,
    measure_phrase,
    pack,
    render_day,
    render_hints,
    render_item,
    render_item_html,
    render_meal,
    render_shopping,
    shorten,
)

CATALOG, IDS = catalog_from_rows(load_foods(), load_measures())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1"),
        (2.0, "2"),
        (0.5, "½"),
        (0.25, "¼"),
        (0.75, "¾"),
        (1.5, "1½"),
        (2.25, "2¼"),
        (0.3, "0,3"),
        (1.2, "1,2"),
        (10, "10"),
    ],
)
def test_format_number(value: float, expected: str) -> None:
    assert format_number(value) == expected


@pytest.mark.parametrize(
    ("name", "quantity", "expected"),
    [
        ("половник", 1, "1 половник"),
        ("половник", 2, "2 половника"),
        ("половник", 4, "4 половника"),
        ("половник", 5, "5 половников"),
        ("половник", 11, "11 половников"),
        ("половник", 12, "12 половников"),
        ("половник", 21, "21 половник"),
        ("половник", 22, "22 половника"),
        ("половник", 0.5, "½ половника"),
        ("половник", 1.5, "1½ половника"),
        ("половник", 0.25, "¼ половника"),
        ("горсть", 1, "1 горсть"),
        ("горсть", 2, "2 горсти"),
        ("горсть", 5, "5 горстей"),
        ("горсть", 0.5, "½ горсти"),
        ("столовая ложка", 1, "1 столовая ложка"),
        ("столовая ложка", 2, "2 столовые ложки"),
        ("столовая ложка", 5, "5 столовых ложек"),
        ("столовая ложка", 0.5, "½ столовой ложки"),
        ("чайная ложка", 3, "3 чайные ложки"),
        ("стакан", 3, "3 стакана"),
        ("яйцо", 2, "2 яйца"),
        ("яйцо", 5, "5 яиц"),
        ("авокадо", 2, "2 авокадо"),
    ],
)
def test_measure_phrase_agrees_with_the_number(name: str, quantity: float, expected: str) -> None:
    assert measure_phrase(name, quantity) == expected


def test_every_real_measure_can_be_phrased_for_any_quantity() -> None:
    names = {m.name_ru for m in load_measures()}
    assert len(names) > 40
    for name in names:
        for quantity in (0.25, 0.5, 1, 1.5, 2, 3, 5, 12, 21):
            phrase = measure_phrase(name, quantity)
            assert phrase.startswith(format_number(quantity))
            assert phrase.split(" ", 1)[1].strip()
            assert not any(ch.isascii() and ch.isalpha() for ch in phrase)


def _meal() -> Meal:
    rice = IDS["rice_white_cooked"]
    measure = CATALOG.measures_for(rice)[0]
    dish = Dish("Рис", (DishItem(rice, measure.id, 2.0),), "Сварите рис.")
    return Meal(MealType.LUNCH, (dish,))


def test_item_line_shows_the_food_and_a_measure_not_grams() -> None:
    meal = _meal()
    assert render_item(CATALOG, meal.dishes[0].items[0]) == "• Рис белый (варёный) — 2 половника"


def test_html_item_line_has_a_category_icon_and_a_bold_measure() -> None:
    item = _meal().dishes[0].items[0]
    assert render_item_html(CATALOG, item) == "🌾 Рис белый (варёный) — <b>2 половника</b>"


def test_every_food_category_has_an_icon() -> None:
    assert set(texts.CATEGORY_ICONS) == set(FoodCategory)


def test_meal_block_has_title_nutrients_ingredients_and_folded_recipe() -> None:
    text = render_meal(CATALOG, _meal())
    assert text.startswith("🍲 <b>Обед</b> · ≈ ")
    assert "ккал\n<i>Б " in text
    assert "<b>Рис</b>" in text
    assert "(≈" not in text  # one dish: its kcal would only repeat the meal line
    assert "🌾 Рис белый (варёный) — <b>2 половника</b>" in text
    assert text.endswith("Сварите рис.</blockquote>")
    assert "<blockquote expandable>" + texts.RECIPE_LABEL in text


def test_dish_kcal_is_shown_only_when_a_meal_has_several_dishes() -> None:
    meal = _meal()
    second = Dish("Салат", meal.dishes[0].items, "")
    text = render_meal(CATALOG, Meal(meal.meal_type, (meal.dishes[0], second)))
    assert text.count("<i>· ≈") == 2


def test_names_and_recipes_are_escaped_for_html() -> None:
    meal = _meal()
    dish = Dish("Рис <b>&</b>", meal.dishes[0].items, "Нагреть до 5 < 7 & подать")
    text = render_meal(CATALOG, Meal(meal.meal_type, (dish,)))
    assert "<b>Рис &lt;b&gt;&amp;&lt;/b&gt;</b>" in text
    assert "5 &lt; 7 &amp; подать" in text
    assert html_text("a<b>") == "a&lt;b&gt;"


def test_long_recipe_is_cut_at_a_word_with_an_ellipsis() -> None:
    long = "слово " * 300
    cut = shorten(long)
    assert len(cut) <= MAX_RECIPE_CHARS + 1
    assert cut.endswith("слово…")
    assert shorten("коротко") == "коротко"


def test_meal_without_a_recipe_has_no_recipe_block() -> None:
    meal = _meal()
    bare = Meal(meal.meal_type, (Dish("Рис", meal.dishes[0].items, ""),))
    text = render_meal(CATALOG, bare)
    assert texts.RECIPE_LABEL not in text
    assert "blockquote" not in text


def test_day_starts_with_a_header_and_numbers_come_from_the_meals() -> None:
    blocks = render_day(CATALOG, 2, [_meal()])
    assert blocks[0].startswith("📅 <b>День 2</b>\n🔥 ")
    assert len(blocks) == 2


def test_hints_are_deduplicated_and_empty_means_no_block() -> None:
    assert render_hints([]) == ""
    hint = BalanceHint(HintKind.VEG_FRUIT)
    block = render_hints([hint, hint, BalanceHint(HintKind.PROTEIN_MEAL, MealType.DINNER)])
    assert block.count("Овощей и фруктов") == 1
    assert "В ужин белка" in block
    assert block.startswith(texts.HINTS_TITLE)


def test_shopping_blocks_are_grouped_by_category() -> None:
    rice = IDS["rice_white_cooked"]
    egg = IDS["egg_boiled"]
    meals = [
        Meal(
            MealType.LUNCH,
            (
                Dish(
                    "d",
                    (
                        DishItem(rice, CATALOG.measures_for(rice)[0].id, 3.0),
                        DishItem(egg, CATALOG.measures_for(egg)[0].id, 2.0),
                    ),
                ),
            ),
        )
    ]
    items = build_shopping_list(CATALOG, [meals], ShoppingConfig())
    blocks = render_shopping(items, 1)
    assert blocks[0].startswith("🛒 <b>Список покупок на 1 день</b>")
    assert any(b.startswith("🥚 <b>Яйца</b>\n• ") for b in blocks)
    assert any(b.startswith("🌾 <b>Крупы и макароны</b>\n• Рис белый (сухой) — ") for b in blocks)


def test_item_without_a_measure_is_listed_without_an_amount() -> None:
    from nutrition_bot.core.shopping import ShoppingItem

    food = CATALOG.get_food(IDS["rice_white_raw"])
    blocks = render_shopping([ShoppingItem(food, 50.0, None, 0.0)], 3)
    assert f"• {food.name_ru} — <b>{texts.SHOPPING_NO_AMOUNT}</b>" in blocks[1]
    assert "на 3 дня</b>" in blocks[0]
    assert blocks[0].endswith("<i>То, что уже есть дома, я не включала.</i>")


def test_pack_respects_the_limit_and_keeps_order() -> None:
    blocks = ["a" * 40, "b" * 40, "c" * 40]
    assert pack(blocks, limit=100) == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40]
    assert pack([], limit=100) == []
    assert pack(["x" * 500], limit=100) == ["x" * 100]
    assert all(len(m) <= 100 for m in pack(["y" * 30] * 20, limit=100))


def test_staples_are_listed_in_their_own_block_at_the_end() -> None:
    from nutrition_bot.core.shopping import ShoppingItem

    rice = CATALOG.get_food(IDS["rice_white_raw"])
    oil = CATALOG.get_food(IDS["sunflower_oil"])
    tbsp = next(m for m in CATALOG.measures_for(oil.id) if m.name_ru == "столовая ложка")
    cup = next(m for m in CATALOG.measures_for(rice.id) if m.name_ru == "стакан")
    items = [
        ShoppingItem(rice, 190.0, cup, 1.0),
        ShoppingItem(oil, 14.0, tbsp, 1.0, is_staple=True),
    ]
    blocks = render_shopping(items, 1)
    assert blocks[-1].startswith(texts.SHOPPING_STAPLES_TITLE)
    assert f"• {oil.name_ru} — " in blocks[-1]
    assert not any(oil.name_ru in b for b in blocks[:-1])  # not repeated under its category
    assert any(b.startswith("🌾 <b>Крупы и макароны</b>\n• ") for b in blocks)


def test_without_staples_there_is_no_staple_block() -> None:
    from nutrition_bot.core.shopping import ShoppingItem

    rice = CATALOG.get_food(IDS["rice_white_raw"])
    blocks = render_shopping([ShoppingItem(rice, 50.0, None, 0.0)], 1)
    assert not any(b.startswith(texts.SHOPPING_STAPLES_TITLE) for b in blocks)


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "1 год"), (2, "2 года"), (5, "5 лет"), (11, "11 лет"), (21, "21 год"), (32, "32 года"),
     (100, "100 лет"), (112, "112 лет")],
)  # fmt: skip
def test_plural_years(count: int, expected: str) -> None:
    from nutrition_bot.handlers.render import plural

    assert plural(count, texts.YEARS_FORMS) == expected


def test_shopping_escapes_food_names() -> None:
    from dataclasses import replace

    from nutrition_bot.core.shopping import ShoppingItem
    from tests.telegram_html import html_problems

    food = replace(CATALOG.get_food(IDS["rice_white_raw"]), name_ru="Рис <особый> & Co")
    blocks = render_shopping([ShoppingItem(food, 50.0, None, 0.0)], 1)
    assert "Рис &lt;особый&gt; &amp; Co" in blocks[1]
    assert not any(html_problems(b) for b in blocks)
