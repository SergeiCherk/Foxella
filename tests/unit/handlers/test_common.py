"""Tests for the small glue helpers of the handlers."""

import pytest

from nutrition_bot.handlers.common import apply_choice, split_parse
from nutrition_bot.handlers.onboarding import parse_number
from nutrition_bot.services.food_parser import Ambiguity, ParsedItem, ParseResult


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("32", 32.0),
        (" 64,5 ", 64.5),
        ("64.5", 64.5),
        ("168 см", 168.0),
        ("70 кг", 70.0),
        ("40 лет", 40.0),
        ("5 лет", 5.0),
    ],
)
def test_parse_number_accepts_plain_numbers_with_units(text: str, expected: float) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1,7 м", "-5", "1e3", "12 13", "около 70", "7 0"])
def test_parse_number_rejects_everything_else(text: str) -> None:
    assert parse_number(text) is None


def _result() -> ParseResult:
    return ParseResult(
        items=[ParsedItem(1, 2.0, frozenset({"кусок"}))],
        ambiguous=[Ambiguity("сыр", (5, 6, 7), 1.0, frozenset())],
    )


def test_split_parse_gives_plain_data() -> None:
    sure, questions = split_parse(_result())
    assert sure == [{"food_id": 1, "qty": 2.0, "words": ["кусок"]}]
    assert questions == [{"text": "сыр", "ids": [5, 6, 7], "qty": 1.0, "words": []}]


@pytest.mark.parametrize(
    ("choice", "expected_ids"),
    [("6", [1, 6]), ("all", [1, 5, 6, 7]), ("skip", [1])],
)
def test_apply_choice(choice: str, expected_ids: list[int]) -> None:
    sure, questions = split_parse(_result())
    apply_choice(sure, questions, choice)
    assert [e["food_id"] for e in sure] == expected_ids
    assert questions == []


def test_a_choice_outside_the_options_is_ignored() -> None:
    sure, questions = split_parse(_result())
    apply_choice(sure, questions, "99")
    assert [e["food_id"] for e in sure] == [1]


def test_non_numeric_choice_is_an_error_for_the_caller_to_catch() -> None:
    sure, questions = split_parse(_result())
    with pytest.raises(ValueError, match="invalid literal"):
        apply_choice(sure, questions, "abc")


def test_no_question_means_nothing_to_do() -> None:
    sure: list = []  # type: ignore[type-arg]
    apply_choice(sure, [], "1")
    assert sure == []


def test_the_same_food_is_not_added_twice() -> None:
    sure = [{"food_id": 5, "qty": 1.0, "words": []}]
    questions = [{"text": "сыр", "ids": [5, 6], "qty": 1.0, "words": []}]
    apply_choice(sure, questions, "all")
    assert [e["food_id"] for e in sure] == [5, 6]
