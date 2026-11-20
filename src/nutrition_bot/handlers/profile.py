"""/profile and /delete_me."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.diet import known_restrictions
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import callback_message, low_kcal_note, sender_id
from nutrition_bot.handlers.onboarding import begin_onboarding
from nutrition_bot.handlers.render import plural
from nutrition_bot.handlers.restrictions import restrictions_phrase

logger = logging.getLogger(__name__)
SessionFactory = async_sessionmaker[AsyncSession]


async def show_profile(
    target: Message, user_id: int, session_factory: SessionFactory, settings: Settings
) -> None:
    """Show the saved data and the norm, or ask to get acquainted first."""
    async with session_factory() as session:
        repo = UserRepository(session)
        profile = await repo.get_profile(user_id)
        restrictions = known_restrictions(await repo.get_restrictions(user_id), settings.diet)
    if profile is None:
        await target.answer(texts.NEED_PROFILE)
        return
    norm = calculate_daily_norm(profile, settings.norms).target
    weight = f"{profile.weight_kg:g}".replace(".", ",")
    note = low_kcal_note(profile, norm.kcal, settings)
    await target.answer(
        texts.PROFILE_VIEW.format(
            sex=texts.SEX_NAMES[profile.sex],
            age=plural(profile.age, texts.YEARS_FORMS),
            height=f"{profile.height_cm:g}".replace(".", ","),
            weight=weight,
            activity=texts.ACTIVITY_NAMES[profile.activity],
            goal=texts.GOAL_NAMES[profile.goal],
            kcal=round(norm.kcal),
            protein=round(norm.protein_g),
            fat=round(norm.fat_g),
            carb=round(norm.carb_g),
        )
        + (
            texts.PROFILE_RESTRICTIONS.format(items=restrictions_phrase(restrictions))
            if restrictions
            else ""
        )
        + (f"\n\n{note}" if note else ""),
        reply_markup=keyboards.profile_keyboard(profile.goal),
    )


async def cmd_profile(
    message: Message, state: FSMContext, session_factory: SessionFactory, settings: Settings
) -> None:
    """Show the profile."""
    await state.clear()
    user_id = sender_id(message)
    if user_id is not None:
        await show_profile(message, user_id, session_factory, settings)


async def on_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Edit = answer the onboarding questions again."""
    message = callback_message(callback)
    await callback.answer()
    if message is not None:
        await begin_onboarding(message, state)


async def cmd_delete_me(message: Message, state: FSMContext) -> None:
    """Ask for confirmation before erasing everything."""
    await state.clear()
    await message.answer(texts.DELETE_CONFIRM, reply_markup=keyboards.delete_keyboard())


async def on_delete_ask(callback: CallbackQuery) -> None:
    """The "delete" button under the profile."""
    message = callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.answer(texts.DELETE_CONFIRM, reply_markup=keyboards.delete_keyboard())


async def on_delete_yes(
    callback: CallbackQuery, state: FSMContext, session_factory: SessionFactory
) -> None:
    """Erase the profile, the pantry and the menu (and any half-finished conversation)."""
    message = callback_message(callback)
    await callback.answer()
    await state.clear()
    async with session_factory() as session:
        found = await UserRepository(session).delete_all(callback.from_user.id)
    logger.info("user data deleted")
    if message is not None:
        await message.answer(
            texts.DELETE_DONE if found else texts.DELETE_NOTHING,
            reply_markup=ReplyKeyboardRemove(),
        )


async def on_delete_no(callback: CallbackQuery) -> None:
    """Cancel the deletion."""
    message = callback_message(callback)
    await callback.answer()
    if message is not None:
        await message.answer(texts.CANCELLED)


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_profile, Command("profile"))
    router.message.register(cmd_profile, F.text == texts.BTN_NAV_PROFILE)
    router.callback_query.register(on_edit, F.data == "profile:edit")
    router.message.register(cmd_delete_me, Command("delete_me"))
    router.callback_query.register(on_delete_ask, F.data == "del:ask")
    router.callback_query.register(on_delete_yes, F.data == "del:yes")
    router.callback_query.register(on_delete_no, F.data == "del:no")
