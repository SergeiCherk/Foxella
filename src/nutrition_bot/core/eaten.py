"""Food we do not know ("лагман"): the language model splits it into foods of our catalog.

The model only names foods, measures and quantities; the code checks them and computes the
calories, as everywhere else. A phrase the model cannot split (not food, nothing similar in the
catalog, or no answer at all) simply stays unknown, so a missing or failing model never breaks
"I ate".
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from nutrition_bot.config import MenuConfig, SlipConfig
from nutrition_bot.core.errors import InvalidLLMResponseError, LLMError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import MAX_PROBLEMS, _extract_json, _parse_item
from nutrition_bot.core.models import DishItem
from nutrition_bot.core.nutrition import item_nutrients

logger = logging.getLogger(__name__)

QUANTITY_STEP = 0.25  # the model's quantities are rounded to quarters of a measure


@dataclass(frozen=True, slots=True)
class EatenRequest:
    """Phrases the parser did not know and the foods the model may split them into."""

    phrases: tuple[str, ...]
    allowed_food_ids: tuple[int, ...]
    feedback: tuple[str, ...] = ()  # problems found in the previous answer


class EatenAnalyzer(Protocol):
    """Anything that can answer an ``EatenRequest`` with raw JSON text (real LLM or a stub)."""

    async def decompose(self, request: EatenRequest) -> str:
        """Return the model's raw answer. Raise ``LLMError`` if it cannot be obtained."""
        ...


Decomposition = dict[str, tuple[DishItem, ...]]


def _round(quantity: float) -> float:
    return max(QUANTITY_STEP, round(quantity / QUANTITY_STEP) * QUANTITY_STEP)


def parse_decomposition(
    raw: str,
    phrases: Sequence[str],
    catalog: Catalog,
    allowed_food_ids: Sequence[int],
    menu_cfg: MenuConfig,
    slip_cfg: SlipConfig,
) -> Decomposition:
    """Validate the model's answer: ``{"foods": [{"phrase", "items": [...]}]}``.

    Returns the items per phrase as asked (an empty tuple: the model says it is not food).
    Phrases the model left out are simply missing. Raises ``InvalidLLMResponseError`` with
    every problem found, so the model can fix them in one retry.
    """
    data = _extract_json(raw)
    entries = data.get("foods") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise InvalidLLMResponseError(["the top level must be a JSON object with a 'foods' list"])
    asked = {p.casefold().strip(): p for p in phrases}
    allowed = set(allowed_food_ids)
    problems: list[str] = []
    found: Decomposition = {}
    for number, entry in enumerate(entries, start=1):
        label = f"food {number}"
        if not isinstance(entry, dict):
            problems.append(f"{label}: must be an object")
            continue
        phrase = entry.get("phrase")
        key = phrase.casefold().strip() if isinstance(phrase, str) else ""
        if key not in asked:
            problems.append(f"{label}: phrase must be one of the given phrases, copied as is")
            continue
        if asked[key] in found:
            problems.append(f"{label}: the phrase {phrase!r} is answered twice")
            continue
        raw_items = entry.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > menu_cfg.max_items_per_dish:
            problems.append(f"{label}: items must be a list of 0 to {menu_cfg.max_items_per_dish}")
            continue
        items: list[DishItem] = []
        for n, raw_item in enumerate(raw_items, start=1):
            item, item_problems = _parse_item(
                f"{label} item {n}", raw_item, catalog, allowed, menu_cfg
            )
            problems += item_problems
            if item is not None:
                items.append(DishItem(item.food_id, item.measure_id, _round(item.quantity)))
        if len({i.food_id for i in items}) != len(items):
            problems.append(f"{label}: the same food appears twice, merge the quantities")
        kcal = sum(item_nutrients(catalog, i).kcal for i in items)
        if kcal > slip_cfg.llm_max_kcal_per_phrase:
            problems.append(
                f"{label}: {kcal:.0f} kcal is too much for one serving, check the quantities"
            )
        found[asked[key]] = tuple(items)
    if problems:
        raise InvalidLLMResponseError(problems[:MAX_PROBLEMS])
    return found


async def decompose_eaten(
    analyzer: EatenAnalyzer,
    catalog: Catalog,
    phrases: Sequence[str],
    allowed_food_ids: Sequence[int],
    menu_cfg: MenuConfig,
    slip_cfg: SlipConfig,
) -> Decomposition:
    """Ask the model what the unknown phrases are made of; only non-empty, valid answers.

    At most ``llm_max_phrases`` phrases are sent; a rejected answer is sent back with its
    problems up to ``llm_max_retries`` times. Any failure gives an empty result.
    """
    asked = tuple(phrases[: slip_cfg.llm_max_phrases])
    if not asked:
        return {}
    feedback: tuple[str, ...] = ()
    for attempt in range(1, slip_cfg.llm_max_retries + 2):
        request = EatenRequest(asked, tuple(allowed_food_ids), feedback)
        try:
            raw = await analyzer.decompose(request)
        except LLMError as error:
            logger.warning("LLM call for eaten food failed (attempt %d): %s", attempt, error)
            return {}
        try:
            found = parse_decomposition(raw, asked, catalog, allowed_food_ids, menu_cfg, slip_cfg)
        except InvalidLLMResponseError as error:
            logger.info("LLM answer for eaten food rejected (attempt %d): %s", attempt, error)
            feedback = tuple(error.problems)
            continue
        return {phrase: items for phrase, items in found.items() if items}
    return {}
