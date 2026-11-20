"""Remembered answers to "which one?" (handlers.common)."""

from nutrition_bot.handlers.common import choice_key, remembered_note, use_remembered
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()


def question(*codes: str, text: str = "курица") -> dict[str, object]:
    return {"text": text, "ids": [IDS[c] for c in codes], "qty": 2.0, "words": ["грудка"]}


def test_the_key_ignores_order_and_repeats() -> None:
    assert choice_key([14, 12, 12]) == choice_key([12, 14]) == "12,14"


def test_a_remembered_answer_becomes_a_sure_item() -> None:
    chicken = question("chicken_breast_raw", "chicken_thigh_raw")
    other = question("sour_cream_15", "sour_cream_20", text="сметана")
    sure: list[dict[str, object]] = []
    questions = [chicken, other]
    choices = {choice_key(chicken["ids"]): IDS["chicken_thigh_raw"]}  # type: ignore[arg-type]
    answered = use_remembered(sure, questions, choices)
    assert questions == [other]
    assert sure == [{"food_id": IDS["chicken_thigh_raw"], "qty": 2.0, "words": ["грудка"]}]
    assert "курица → Куриное бедро без кожи (сырое)" in remembered_note(CATALOG, answered)


def test_a_stale_answer_is_ignored() -> None:
    chicken = question("chicken_breast_raw", "chicken_thigh_raw")
    questions = [chicken]
    stale = {choice_key(chicken["ids"]): 999_999}  # type: ignore[arg-type]
    assert use_remembered([], questions, stale) == []
    assert questions == [chicken]
    assert remembered_note(CATALOG, []) == ""


def test_the_note_escapes_what_the_person_typed() -> None:
    chicken = question("chicken_breast_raw", "chicken_thigh_raw", text="<b>курица</b>")
    answered = [{**chicken, "chosen": IDS["chicken_breast_raw"]}]
    assert "&lt;b&gt;курица&lt;/b&gt;" in remembered_note(CATALOG, answered)
