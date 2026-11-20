"""Tests for the free-text food parser, using the real alias list."""

import pytest

from nutrition_bot.config import ParserConfig
from nutrition_bot.core.models import Measure
from nutrition_bot.db.seed import catalog_from_rows, load_foods, load_measures
from nutrition_bot.services.food_parser import FoodParser, choose_measure, lemma

FOODS = load_foods()
CATALOG, IDS = catalog_from_rows(FOODS, load_measures())
ALIASES: dict[str, list[int]] = {}
for row in FOODS:
    for alias in row.aliases:
        ALIASES.setdefault(alias, []).append(IDS[row.code])
PARSER = FoodParser(ALIASES, ParserConfig())


def codes(result_items: list) -> list[str]:  # type: ignore[type-arg]
    return [CATALOG.get_food(i.food_id).code for i in result_items]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("гречка", ["buckwheat_raw"]),
        ("Гречки", ["buckwheat_raw"]),
        ("греча", ["buckwheat_raw"]),
        ("гречневая крупа", ["buckwheat_raw"]),
        ("куриная грудка", ["chicken_breast_raw"]),
        ("куриной грудки без кожи", ["chicken_breast_raw"]),
        ("варёные яйца", ["egg_boiled"]),
        ("вареные яйца", ["egg_boiled"]),  # ё typed as е
        ("яйца", ["egg_raw"]),
        ("рис, гречка и яйца", ["rice_white_raw", "buckwheat_raw", "egg_raw"]),
        ("рис; гречка\nяйца", ["rice_white_raw", "buckwheat_raw", "egg_raw"]),
        ("рис + гречка", ["rice_white_raw", "buckwheat_raw"]),
        ("ГРЕЧКА", ["buckwheat_raw"]),
    ],
)
def test_phrases_are_recognised_in_any_word_form(text: str, expected: list[str]) -> None:
    result = PARSER.parse(text)
    assert codes(result.items) == expected
    assert result.ambiguous == []
    assert result.unknown == []


def test_a_typo_is_forgiven() -> None:
    assert codes(PARSER.parse("греука").items) == []  # too far off
    assert codes(PARSER.parse("гречкаа").items) == ["buckwheat_raw"]
    assert codes(PARSER.parse("брокколи").items) == ["broccoli"]
    assert codes(PARSER.parse("броколи").items) == ["broccoli"]


@pytest.mark.parametrize(
    ("text", "quantity"),
    [
        ("2 банана", 2.0),
        ("банан", 1.0),
        ("полтора банана", 1.5),
        ("пол банана", 0.5),
        ("1/2 банана", 0.5),
        ("½ банана", 0.5),
        ("1,5 банана", 1.5),
        ("пара бананов", 2.0),
        ("три банана", 3.0),
        ("банан 2 шт", 2.0),
    ],
)
def test_quantities(text: str, quantity: float) -> None:
    (item,) = PARSER.parse(text).items
    assert item.quantity == quantity


def test_decimal_comma_is_not_a_separator() -> None:
    result = PARSER.parse("1,5 банана, овсянку")
    assert codes(result.items) == ["banana", "oat_flakes_dry"]
    assert result.unknown == []


def test_ambiguous_phrase_lists_the_options() -> None:
    result = PARSER.parse("творог, гречка")
    assert codes(result.items) == ["buckwheat_raw"]
    (question,) = result.ambiguous
    assert {CATALOG.get_food(i).code for i in question.food_ids} == {
        "cottage_0",
        "cottage_5",
        "cottage_9",
    }
    assert question.text == "творог"


def test_a_more_specific_alias_wins_over_a_general_one() -> None:
    assert codes(PARSER.parse("варёная картошка").items) == ["potato_boiled"]
    assert codes(PARSER.parse("картошка").items) == ["potato_raw"]


def test_unknown_phrases_are_reported_not_invented() -> None:
    result = PARSER.parse("гречка, бетон, ")
    assert codes(result.items) == ["buckwheat_raw"]
    assert result.unknown == ["бетон"]


@pytest.mark.parametrize("text", ["", "   ", ",,,", "!!!", "12345", "а"])
def test_garbage_gives_nothing(text: str) -> None:
    result = PARSER.parse(text)
    assert (result.items, result.ambiguous) == ([], [])


def test_the_same_food_twice_is_listed_once() -> None:
    assert codes(PARSER.parse("гречка, греча, гречневая крупа").items) == ["buckwheat_raw"]


def test_long_input_is_cut() -> None:
    parser = FoodParser(ALIASES, ParserConfig(max_chunks=2))
    assert len(parser.parse("рис, гречка, яйца, банан").items) == 2
    short = FoodParser(ALIASES, ParserConfig(max_text_length=5))
    assert short.parse("рис, гречка").items[0].food_id == IDS["rice_white_raw"]
    assert len(short.parse("рис, гречка").items) == 1


def test_empty_alias_list_never_matches() -> None:
    parser = FoodParser({}, ParserConfig())
    assert parser.parse("гречка").unknown == ["гречка"]


def test_words_next_to_the_food_are_kept_as_hints() -> None:
    (item,) = PARSER.parse("2 куска шоколада").items
    assert "кусок" in item.words


def test_lemma_handles_yo_and_forms() -> None:
    assert lemma("Яйца") == "яйцо"
    assert lemma("варёные") == lemma("вареные")


def test_choose_measure_prefers_the_named_one() -> None:
    measures = [Measure(2, 1, "кусок", 100.0), Measure(1, 1, "ломтик", 30.0)]
    assert choose_measure(measures, frozenset({"кусок"})) == measures[0]
    assert choose_measure(measures, frozenset({"ломтик"})) == measures[1]
    assert choose_measure(measures, frozenset()) == measures[1]  # the first by id
    assert choose_measure([], frozenset({"кусок"})) is None
    two_words = [Measure(5, 1, "столовая ложка", 15.0)]
    assert choose_measure(two_words, frozenset({"ложка"})) == two_words[0]


# ---- ready dishes and phrases with "с"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("борщ", ["borscht"]),
        ("тарелка борща", ["borscht"]),
        ("пельмени", ["pelmeni"]),
        ("2 куска пиццы", ["pizza_cheese"]),
        ("шаурма", ["shawarma"]),
        ("бургер", ["hamburger"]),
        ("картошка фри", ["french_fries"]),
        ("жареная картошка", ["fried_potato"]),
        ("макароны по-флотски", ["navy_pasta"]),
        ("селёдка под шубой", ["herring_under_fur"]),
        ("доширак", ["instant_noodles"]),
        ("бутылка пива", ["beer"]),
        ("чай", ["tea"]),
    ],
)
def test_ready_dishes_are_recognised(text: str, expected: list[str]) -> None:
    result = PARSER.parse(text)
    assert codes(result.items) == expected
    assert not result.unknown


def test_joiners_inside_an_alias_do_not_break_it() -> None:
    assert codes(PARSER.parse("овсянка на молоке").items) == ["oatmeal_milk"]
    assert codes(PARSER.parse("вареники с творогом").items) == ["vareniki_cottage"]
    assert codes(PARSER.parse("макароны с фаршем").items) == ["navy_pasta"]


def test_with_joins_two_foods_unless_the_phrase_is_one_alias() -> None:
    result = PARSER.parse("тарелка борща со сметаной")
    assert codes(result.items) == ["borscht"]
    assert [CATALOG.get_food(i).code for i in result.ambiguous[0].food_ids] == [
        "sour_cream_15",
        "sour_cream_20",
    ]
    assert codes(PARSER.parse("3 блина со сгущёнкой").items) == ["bliny", "condensed_milk"]
    first, second = PARSER.parse("3 блина со сгущёнкой").items
    assert (first.quantity, second.quantity) == (3, 1)  # the number belongs to the first food


def test_number_words_in_any_case() -> None:
    (item,) = PARSER.parse("яичница из двух яиц").items
    assert (CATALOG.get_food(item.food_id).code, item.quantity) == ("fried_eggs", 2)
    assert "яйцо" in item.words  # the measure: two eggs, not two portions
    assert PARSER.parse("трёх пельменей").items[0].quantity == 3


def test_a_dish_with_several_kinds_asks_which() -> None:
    (choice,) = PARSER.parse("вареники").ambiguous
    assert {CATALOG.get_food(i).code for i in choice.food_ids} == {
        "vareniki_potato",
        "vareniki_cottage",
    }
