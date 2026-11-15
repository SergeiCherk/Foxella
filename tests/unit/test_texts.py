"""Tests for bot texts: the slip messages must stay calm, kind and free of blame."""

import pytest

from nutrition_bot.core.balance import HintKind
from nutrition_bot.core.models import FoodCategory, MealType
from nutrition_bot.core.slip import SlipOutcome
from nutrition_bot.texts import HINT_TEXTS, MEAL_IN, SHOPPING_TITLES, SLIP_TEXTS

# Word stems that must never appear in messages about eating off-plan (matched case-insensitively).
FORBIDDEN_STEMS = [
    "срыв", "сорва", "нарушил", "нарушен", "провал", "виноват", "вина ", "вины", "стыд",
    "плохо", "ужасно", "наказ", "штраф", "обжор", "объел", "переел", "слабоволи",
    "должен", "должна", "обязан", "немедленно", "срочно", "компенсируй", "отработ",
]  # fmt: skip


def test_every_outcome_has_a_text() -> None:
    assert set(SLIP_TEXTS) == set(SlipOutcome)


@pytest.mark.parametrize("outcome", list(SlipOutcome))
def test_slip_texts_contain_no_blame_or_pressure(outcome: SlipOutcome) -> None:
    text = SLIP_TEXTS[outcome].lower() + " "
    found = [stem for stem in FORBIDDEN_STEMS if stem in text]
    assert not found, f"{outcome}: forbidden wording {found}"


@pytest.mark.parametrize("outcome", list(SlipOutcome))
def test_slip_texts_format_cleanly(outcome: SlipOutcome) -> None:
    text = SLIP_TEXTS[outcome].format(excess_kcal=350, per_day_kcal=117)
    assert "{" not in text
    assert "}" not in text
    assert text.strip() == text


def test_texts_with_numbers_name_both_numbers() -> None:
    for outcome in (SlipOutcome.FULL, SlipOutcome.PARTIAL):
        assert "{excess_kcal}" in SLIP_TEXTS[outcome]
        assert "{per_day_kcal}" in SLIP_TEXTS[outcome]


def test_reassurance_comes_first_when_there_was_an_excess() -> None:
    for outcome in (SlipOutcome.FULL, SlipOutcome.PARTIAL, SlipOutcome.NO_ROOM):
        assert SLIP_TEXTS[outcome].startswith("Всё в порядке")


def test_texts_never_encourage_skipping_meals_or_hunger() -> None:
    assert "голодать не придётся" in SLIP_TEXTS[SlipOutcome.FULL]
    assert "пропускать приёмы пищи" in SLIP_TEXTS[SlipOutcome.UNDER_PLAN]
    for text in SLIP_TEXTS.values():
        assert "поголод" not in text.lower()
        assert "не ешь" not in text.lower()


# ---------- balance hints and shopping list ----------

# Hints are suggestions: no orders, no amounts, nothing about weight loss pressure.
HINT_FORBIDDEN = [*FORBIDDEN_STEMS, "нужно", "надо", "необходимо", "обязательно", "грамм", " г "]


def test_every_hint_kind_has_a_text() -> None:
    assert set(HINT_TEXTS) == set(HintKind)


def test_every_meal_type_and_category_has_a_name() -> None:
    assert set(MEAL_IN) == set(MealType)
    assert set(SHOPPING_TITLES) == set(FoodCategory)


@pytest.mark.parametrize("kind", list(HintKind))
def test_hint_texts_are_calm_and_show_no_amounts(kind: HintKind) -> None:
    text = HINT_TEXTS[kind].lower() + " "
    assert not [stem for stem in HINT_FORBIDDEN if stem in text]
    assert not any(ch.isdigit() for ch in text)


@pytest.mark.parametrize("kind", list(HintKind))
def test_hint_texts_format_cleanly(kind: HintKind) -> None:
    text = HINT_TEXTS[kind].format(meal=MEAL_IN[MealType.LUNCH])
    assert "{" not in text
    assert "}" not in text
    assert text.strip() == text


def test_meal_hint_names_the_meal_and_day_hint_does_not() -> None:
    assert "{meal}" in HINT_TEXTS[HintKind.PROTEIN_MEAL]
    assert "{meal}" not in HINT_TEXTS[HintKind.PROTEIN_DAY]


# ---- notes, term check, protection messages: same calm tone, no pressure


def test_new_user_facing_texts_stay_calm() -> None:
    from nutrition_bot import texts

    names = [
        n
        for n in dir(texts)
        if n.startswith(("GOAL_", "LOW_KCAL", "MENU_BUSY", "MENU_COOLDOWN", "STALE_"))
    ]
    assert len(names) >= 10
    for name in names:
        value = getattr(texts, name)
        if not isinstance(value, str):
            continue
        low = value.lower() + " "
        assert not [s for s in FORBIDDEN_STEMS if s in low], name


def test_new_texts_format_cleanly() -> None:
    from nutrition_bot import texts

    samples = [
        texts.LOW_KCAL_NOTE.format(minimum=1200, who="женщин"),
        texts.GOAL_ASK_TARGET.format(weight="64,5"),
        texts.GOAL_BAD_WEEKS.format(max_weeks=104),
        texts.GOAL_OK.format(pace="0,5"),
        texts.GOAL_TOO_FAST.format(weeks_asked=4, pace_asked="2,4", safe="0,34", weeks=28),
        texts.MENU_COOLDOWN.format(seconds=30),
    ]
    for text in samples:
        assert "{" not in text
        assert "}" not in text
        assert text == text.strip()
