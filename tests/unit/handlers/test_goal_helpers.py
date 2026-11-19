"""Small pure helpers of the term check and the keyboards that offer it."""

import pytest

from nutrition_bot import texts
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import low_kcal_note
from nutrition_bot.handlers.goal import _kg, parse_weeks


@pytest.mark.parametrize(
    ("text", "expected"),
    [("12", 12), (" 8 ", 8), ("12 недель", 12), ("3 недели", 3), ("1 неделя", 1), ("12 нед.", 12),
     ("12н", 12), ("0", 0), ("104", 104)],
)  # fmt: skip
def test_parse_weeks_accepts_whole_numbers(text: str, expected: int) -> None:
    assert parse_weeks(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1,5", "-3", "две недели", "12 кг", "12345", "1 2"])
def test_parse_weeks_rejects_everything_else(text: str) -> None:
    assert parse_weeks(text) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.5, "0,5"), (0.25, "0,25"), (2.0, "2"), (0.1875, "0,19"), (0.0, "0"), (12.375, "12,38")],
)
def test_kg_formatting_uses_a_decimal_comma(value: float, expected: str) -> None:
    assert _kg(value) == expected


def datas(markup) -> list[str]:  # type: ignore[no-untyped-def]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.parametrize("goal", [Goal.LOSE, Goal.GAIN])
def test_the_term_check_is_offered_for_goals_that_change_weight(goal: Goal) -> None:
    assert "goalcheck:start" in datas(keyboards.after_onboarding_keyboard(goal))
    assert "goalcheck:start" in datas(keyboards.profile_keyboard(goal))


@pytest.mark.parametrize("goal", [Goal.MAINTAIN, None])
def test_the_term_check_is_not_offered_otherwise(goal: Goal | None) -> None:
    assert datas(keyboards.after_onboarding_keyboard(goal)) == ["menu:start"]
    assert datas(keyboards.profile_keyboard(goal)) == ["profile:edit", "del:ask"]


def test_menu_button_always_comes_first_and_delete_last() -> None:
    assert datas(keyboards.after_onboarding_keyboard(Goal.LOSE))[0] == "menu:start"
    assert datas(keyboards.profile_keyboard(Goal.LOSE))[-1] == "del:ask"


def test_weeks_keyboard() -> None:
    assert datas(keyboards.weeks_keyboard((4, 8))) == ["weeks:4", "weeks:8"]


def test_low_kcal_note_texts(settings) -> None:  # type: ignore[no-untyped-def]
    tiny_woman = Profile(Sex.FEMALE, 80, 150.0, 45.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    note = low_kcal_note(tiny_woman, 991.8, settings)
    assert "1200 ккал для женщин" in note
    assert "врачом" in note
    tiny_man = Profile(Sex.MALE, 90, 150.0, 40.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    assert "1500 ккал для мужчин" in low_kcal_note(tiny_man, 1071.0, settings)
    assert low_kcal_note(tiny_woman, 1200.0, settings) == ""
    assert texts.LOW_KCAL_NOTE.startswith("⚠️ <b>Обрати внимание")
