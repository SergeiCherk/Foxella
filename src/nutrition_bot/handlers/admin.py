"""/admin: usage statistics for the bot owner (``ADMIN_IDS`` in .env).

For anyone else the command does not exist: the filter fails and the message reaches the usual
fallback. Only counts are shown, never ids, names or anything a person wrote.
"""

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot.config import Settings
from nutrition_bot.core.menu import DishGenerator
from nutrition_bot.core.metrics import overview
from nutrition_bot.db.repositories.events import EventRepository
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import callback_message
from nutrition_bot.handlers.render import render_overview

SessionFactory = async_sessionmaker[AsyncSession]


def is_admin(event: Message | CallbackQuery, settings: Settings) -> bool:
    """True only for the Telegram ids listed in ``ADMIN_IDS``."""
    return event.from_user is not None and event.from_user.id in settings.admin_ids


async def send_overview(
    target: Message, session_factory: SessionFactory, settings: Settings, llm: DishGenerator
) -> None:
    """Count everything now and send it with a refresh button."""
    async with session_factory() as session:
        users = await UserRepository(session).all_facts()
        events = await EventRepository(session).all_events()
    now = datetime.now(UTC)
    model = settings.llm_model if getattr(llm, "available", False) else None
    await target.answer(
        render_overview(overview(users, events, now), now, model),
        reply_markup=keyboards.admin_keyboard(),
    )


async def cmd_admin(
    message: Message,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    llm: DishGenerator,
) -> None:
    """/admin"""
    await state.clear()
    await send_overview(message, session_factory, settings, llm)


async def on_refresh(
    callback: CallbackQuery, session_factory: SessionFactory, settings: Settings, llm: DishGenerator
) -> None:
    """The "refresh" button: fresh numbers in a new message."""
    await callback.answer()
    message = callback_message(callback)
    if message is not None:
        await send_overview(message, session_factory, settings, llm)


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_admin, Command("admin"), is_admin)
    router.callback_query.register(on_refresh, F.data == "admin:refresh", is_admin)
