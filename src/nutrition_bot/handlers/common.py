"""Helpers shared by several handler modules. No business logic: only glue code."""

import logging
from collections.abc import Sequence
from typing import Any

from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.models import Profile, Sex
from nutrition_bot.core.norms import is_below_sex_minimum
from nutrition_bot.db.repositories.events import EventRepository

logger = logging.getLogger(__name__)

Entry = dict[str, Any]  # {"food_id", "qty", "words"} for a sure item, plus "ids"/"text" if unsure


async def track(
    session_factory: async_sessionmaker[AsyncSession], user_id: int, event: EventName
) -> None:
    """Record a usage event. A failure of the statistics must never break the conversation."""
    try:
        async with session_factory() as session:
            await EventRepository(session).record(user_id, event)
    except SQLAlchemyError:
        logger.warning("could not record the %s event", event.value)


def callback_message(callback: CallbackQuery) -> Message | None:
    """The message the pressed button belongs to (``None`` if Telegram no longer has it)."""
    message = callback.message
    return message if isinstance(message, Message) else None


def sender_id(message: Message) -> int | None:
    """Telegram id of the person who wrote the message (``None`` for channel posts)."""
    return message.from_user.id if message.from_user else None


def split_parse(result: Any) -> tuple[list[Entry], list[Entry]]:
    """``ParseResult`` -> (sure entries, questions) in a form that FSM storage can keep."""
    sure = [
        {"food_id": i.food_id, "qty": i.quantity, "words": sorted(i.words)} for i in result.items
    ]
    questions = [
        {"text": a.text, "ids": list(a.food_ids), "qty": a.quantity, "words": sorted(a.words)}
        for a in result.ambiguous
    ]
    return sure, questions


def apply_choice(sure: list[Entry], questions: list[Entry], choice: str) -> None:
    """Answer the first question: a food id, ``all`` (every option) or ``skip``."""
    if not questions:
        return
    question = questions.pop(0)
    if choice == "skip":
        return
    ids = question["ids"] if choice == "all" else [int(choice)]
    for food_id in ids:
        if food_id in question["ids"] and all(e["food_id"] != food_id for e in sure):
            sure.append({"food_id": food_id, "qty": question["qty"], "words": question["words"]})


def options_of(catalog: Catalog, question: Entry) -> Sequence[tuple[int, str]]:
    """(food id, display name) for each option of a question."""
    return [(i, catalog.get_food(i).name_ru) for i in question["ids"]]


def low_kcal_note(profile: Profile, kcal: float, settings: Settings) -> str:
    """The doctor note for a norm under the absolute minimum, or an empty string."""
    if not is_below_sex_minimum(profile.sex, kcal, settings.norms):
        return ""
    minimum = (
        settings.norms.min_kcal_male if profile.sex is Sex.MALE else settings.norms.min_kcal_female
    )
    return texts.LOW_KCAL_NOTE.format(
        minimum=round(minimum), who=texts.LOW_KCAL_WHO[profile.sex.value]
    )
