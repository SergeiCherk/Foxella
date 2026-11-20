"""Food restrictions in the profile: toggles under one message, then "Готово"."""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.diet import known_restrictions
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import callback_message

logger = logging.getLogger(__name__)
SessionFactory = async_sessionmaker[AsyncSession]


def restrictions_phrase(codes: list[str]) -> str:
    """ "без мяса, без орехов" for the profile and the confirmation."""
    return ", ".join(
        texts.RESTRICTION_LABELS[c].lower() for c in codes if c in texts.RESTRICTION_LABELS
    )


async def on_show(
    callback: CallbackQuery, session_factory: SessionFactory, settings: Settings
) -> None:
    """Show the toggles with the current choice."""
    message = callback_message(callback)
    await callback.answer()
    if message is None:
        return
    async with session_factory() as session:
        repo = UserRepository(session)
        if await repo.get_profile(callback.from_user.id) is None:
            await message.answer(texts.NEED_PROFILE)
            return
        current = known_restrictions(
            await repo.get_restrictions(callback.from_user.id), settings.diet
        )
    await message.answer(
        texts.RESTRICTIONS_ASK,
        reply_markup=keyboards.restrictions_keyboard(list(settings.diet.rules), current),
    )


async def on_toggle(
    callback: CallbackQuery, session_factory: SessionFactory, settings: Settings
) -> None:
    """Switch one restriction on or off and update the buttons in place."""
    message = callback_message(callback)
    code = (callback.data or "").removeprefix("diet:t:")
    if code not in settings.diet.rules:
        await callback.answer()
        return
    async with session_factory() as session:
        repo = UserRepository(session)
        current = known_restrictions(
            await repo.get_restrictions(callback.from_user.id), settings.diet
        )
        chosen = [c for c in current if c != code] if code in current else [*current, code]
        chosen = known_restrictions(chosen, settings.diet)
        await repo.set_restrictions(callback.from_user.id, chosen)
    await callback.answer()
    if message is not None:
        try:
            await message.edit_reply_markup(
                reply_markup=keyboards.restrictions_keyboard(list(settings.diet.rules), chosen)
            )
        except TelegramAPIError:  # the message is too old to edit: the choice is saved anyway
            logger.info("restriction buttons could not be updated")


async def on_done(
    callback: CallbackQuery, session_factory: SessionFactory, settings: Settings
) -> None:
    """Confirm what is saved."""
    message = callback_message(callback)
    await callback.answer()
    if message is None:
        return
    async with session_factory() as session:
        codes = known_restrictions(
            await UserRepository(session).get_restrictions(callback.from_user.id), settings.diet
        )
    if codes:
        await message.answer(texts.RESTRICTIONS_SAVED.format(items=restrictions_phrase(codes)))
    else:
        await message.answer(texts.RESTRICTIONS_NONE)


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.callback_query.register(on_show, F.data == "diet:show")
    router.callback_query.register(on_toggle, F.data.startswith("diet:t:"))
    router.callback_query.register(on_done, F.data == "diet:done")
