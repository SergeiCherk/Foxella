"""core.eaten: unknown eaten food split by the model into our foods, checked by code."""

import json
from typing import Any

import pytest

from nutrition_bot.config import MenuConfig, SlipConfig
from nutrition_bot.core.eaten import decompose_eaten, parse_decomposition
from nutrition_bot.core.errors import InvalidLLMResponseError, LLMError
from nutrition_bot.core.menu import menu_food_ids
from nutrition_bot.services.llm import FakeLLM
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()
ALLOWED = menu_food_ids(CATALOG)
MENU, SLIP = MenuConfig(), SlipConfig()


def item(code: str, quantity: float = 1.0, measure: int = 0) -> dict[str, Any]:
    food_id = IDS[code]
    return {"food_id": food_id, "measure_id": CATALOG.measures_for(food_id)[measure].id,
            "quantity": quantity}  # fmt: skip


def answer(*foods: tuple[str, list[dict[str, Any]]]) -> str:
    return json.dumps({"foods": [{"phrase": p, "items": i} for p, i in foods]}, ensure_ascii=False)


LAGMAN = [item("pasta_cooked", 2), item("beef_lean_cooked"), item("bell_pepper"),
          item("sunflower_oil")]  # fmt: skip


def parse(raw: str, phrases: tuple[str, ...] = ("лагман",)) -> dict[str, Any]:
    return parse_decomposition(raw, phrases, CATALOG, ALLOWED, MENU, SLIP)


def test_a_valid_answer_gives_the_items_per_phrase() -> None:
    found = parse(answer(("Лагман ", LAGMAN), ("кирпич", [])), ("лагман", "кирпич"))
    assert [i.food_id for i in found["лагман"]] == [IDS[c] for c in
            ("pasta_cooked", "beef_lean_cooked", "bell_pepper", "sunflower_oil")]  # fmt: skip
    assert found["кирпич"] == ()  # the model says it is not food


def test_quantities_are_rounded_to_quarters() -> None:
    (only,) = parse(answer(("лагман", [item("pasta_cooked", 1.3)])))["лагман"]
    assert only.quantity == 1.25


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ("not json", "not valid JSON"),
        ("[1]", "JSON object with a 'foods' list"),
        (answer(("плов", LAGMAN)), "one of the given phrases"),
        (answer(("лагман", LAGMAN), ("лагман", LAGMAN)), "answered twice"),
        (answer(("лагман", [item("borscht")])), "food_id"),  # a ready dish is not allowed
        (answer(("лагман", [item("pasta_cooked"), item("pasta_cooked")])), "appears twice"),
        (answer(("лагман", [item("walnuts", 20)])), "too much for one serving"),
        (json.dumps({"foods": [{"phrase": "лагман", "items": "pasta"}]}), "items must be"),
        (json.dumps({"foods": ["лагман"]}), "must be an object"),
    ],
)
def test_bad_answers_are_refused_with_the_reason(raw: str, problem: str) -> None:
    with pytest.raises(InvalidLLMResponseError) as error:
        parse(raw)
    assert any(problem in p for p in error.value.problems), error.value.problems


async def test_a_refused_answer_is_sent_back_once_with_its_problems() -> None:
    llm = FakeLLM(eaten=[answer(("плов", LAGMAN)), answer(("лагман", LAGMAN))])
    found = await decompose_eaten(llm, CATALOG, ["лагман"], ALLOWED, MENU, SLIP)
    assert len(found["лагман"]) == 4
    assert llm.eaten_requests[0].feedback == ()
    assert any("given phrases" in p for p in llm.eaten_requests[1].feedback)


async def test_two_bad_answers_or_a_failure_give_nothing() -> None:
    bad = answer(("плов", LAGMAN))
    assert await decompose_eaten(FakeLLM(eaten=[bad, bad]), CATALOG, ["лагман"], ALLOWED,
                                 MENU, SLIP) == {}  # fmt: skip
    assert await decompose_eaten(FakeLLM(eaten=[LLMError("down")]), CATALOG, ["лагман"],
                                 ALLOWED, MENU, SLIP) == {}  # fmt: skip


async def test_not_food_is_left_out_and_only_a_few_phrases_are_sent() -> None:
    llm = FakeLLM(eaten=[answer(("лагман", LAGMAN), ("кирпич", []))])
    phrases = ["лагман", "кирпич", "а", "б", "в"]
    found = await decompose_eaten(llm, CATALOG, phrases, ALLOWED, MENU, SLIP)
    assert list(found) == ["лагман"]
    assert llm.eaten_requests[0].phrases == ("лагман", "кирпич", "а")
    assert await decompose_eaten(llm, CATALOG, [], ALLOWED, MENU, SLIP) == {}
