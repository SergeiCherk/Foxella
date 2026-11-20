"""core.recipe_check: hidden calories, amounts and contacts in what the model writes."""

from collections.abc import Sequence

import pytest

from nutrition_bot.core.recipe_check import Mention, recipe_food_problems, text_problems
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()


class ScriptedFinder:
    """Returns the given mentions whatever the text is."""

    def __init__(self, *mentions: Mention) -> None:
        self.mentions = mentions

    def find(self, text: str) -> Sequence[Mention]:
        return self.mentions


def mention(*codes: str, words: str = "x", after_number: bool = False) -> Mention:
    return Mention(words, frozenset(IDS[c] for c in codes), after_number)


def problems(*mentions: Mention, items: Sequence[str], forbidden: Sequence[str] = ()) -> list[str]:
    return recipe_food_problems(
        "dish 1",
        "recipe",
        [IDS[c] for c in items],
        CATALOG,
        ScriptedFinder(*mentions),
        [IDS[c] for c in forbidden],
    )


# ---- contacts, calories in the name, amounts


@pytest.mark.parametrize(
    "text",
    [
        "Подробнее на https://example.com",
        "Смотрите www.recipes.ru",
        "Канал t.me/foodchannel",
        "Пишите @super_chef",
        "Почта chef@mail.ru",
        "Сайт vkusno.рф",
        "Звоните +7 (900) 123-45-67",
    ],
)
def test_contacts_are_refused_in_the_recipe(text: str) -> None:
    assert any("no links" in p for p in text_problems("dish 1", "Омлет", text))


def test_contacts_and_calories_are_refused_in_the_name() -> None:
    assert any("no links" in p for p in text_problems("dish 1", "Омлет @chef", "Взбейте."))
    named = text_problems("d", "Омлет 300 ккал", "x")
    assert any("name must not mention calories" in p for p in named)


@pytest.mark.parametrize(
    "text", ["Возьмите 100 г риса.", "Добавьте 2 ст. ложки масла.", "Налейте 1,5 стакана воды.",
             "Положите 3 ломтика сыра.", "Нужно 200 мл молока."],
)  # fmt: skip
def test_amounts_are_refused(text: str) -> None:
    assert any("amounts" in p for p in text_problems("dish 1", "Блюдо", text))


@pytest.mark.parametrize(
    "text", ["Варите 10 минут.", "Запекайте при 180 градусах 25 минут.", "Подавайте сразу."]
)
def test_time_and_temperature_are_fine(text: str) -> None:
    assert text_problems("dish 1", "Блюдо", text) == []


# ---- foods named in the recipe


def test_a_calorie_dense_food_missing_from_the_items_is_hidden_calories() -> None:
    found = problems(mention("sour_cream_15", words="сметаной"), items=["potato_boiled"])
    assert found == [
        "dish 1: recipe mentions «сметаной», but it is not in items; "
        "add it to items or remove it from the recipe"
    ]


def test_a_light_food_missing_from_the_items_is_fine() -> None:
    assert problems(mention("bell_pepper", "lemon"), items=["potato_boiled"]) == []


def test_a_food_in_the_items_is_fine_and_raw_and_cooked_count_as_one() -> None:
    assert problems(mention("buckwheat_raw", words="гречку"), items=["buckwheat_cooked"]) == []
    assert problems(mention("sunflower_oil", "butter"), items=["sunflower_oil"]) == []


def test_an_amount_next_to_a_food_of_the_dish_is_refused() -> None:
    found = problems(mention("egg_raw", words="яйца", after_number=True), items=["egg_boiled"])
    assert len(found) == 1
    assert "amounts like «яйца»" in found[0]


def test_a_forbidden_food_is_named_as_such() -> None:
    found = problems(mention("cheese_hard", words="сыром"), items=["pasta_cooked"],
                     forbidden=["cheese_hard"])  # fmt: skip
    assert "which this person does not eat" in found[0]


def test_an_alias_only_partly_forbidden_is_judged_as_hidden_calories() -> None:
    # "масло": butter is forbidden (dairy), but sunflower oil is fine
    found = problems(mention("butter", "sunflower_oil", words="масле"), items=["potato_boiled"],
                     forbidden=["butter"])  # fmt: skip
    assert "not in items" in found[0]


def test_each_problem_is_reported_once() -> None:
    twice = mention("sour_cream_15", words="сметаной")
    assert len(problems(twice, twice, items=["potato_boiled"])) == 1


def test_unknown_food_ids_are_ignored() -> None:
    ghost = Mention("призрак", frozenset({999_999}))
    assert problems(ghost, items=["potato_boiled"]) == []
