"""/shopping: the shopping list for the latest menu."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.errors import NutritionError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import staple_food_ids
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.shopping import build_shopping_list
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers.common import callback_message, sender_id, track
from nutrition_bot.handlers.render import pack, render_shopping

logger = logging.getLogger(__name__)
SessionFactory = async_sessionmaker[AsyncSession]


async def send_shopping(
    target: Message,
    user_id: int,
    session_factory: SessionFactory,
    catalog: Catalog,
    settings: Settings,
) -> None:
    """Build the list from the saved menu, leaving out what the user already has."""
    async with session_factory() as session:
        repo = UserRepository(session)
        menu = await repo.get_menu(user_id)
        owned = await repo.get_pantry(user_id)
    if not menu:
        await target.answer(texts.NO_MENU)
        return
    try:
        staples = staple_food_ids(catalog, settings.menu.staple_codes)
        items = build_shopping_list(catalog, menu, settings.shopping, owned, staples)
    except NutritionError:
        logger.exception("saved menu does not match the catalog")
        await target.answer(texts.NO_MENU)
        return
    if not items:
        await target.answer(texts.SHOPPING_ALL_OWNED)
        return
    for text in pack(render_shopping(items, len(menu))):
        await target.answer(text)
    await track(session_factory, user_id, EventName.SHOPPING_RECEIVED)


async def cmd_shopping(
    message: Message,
    state: FSMContext,
    session_factory: SessionFactory,
    catalog: Catalog,
    settings: Settings,
) -> None:
    """/shopping"""
    await state.clear()
    user_id = sender_id(message)
    if user_id is not None:
        await send_shopping(message, user_id, session_factory, catalog, settings)


async def on_shop_button(
    callback: CallbackQuery,
    session_factory: SessionFactory,
    catalog: Catalog,
    settings: Settings,
) -> None:
    """The "shopping list" button under a menu."""
    message = callback_message(callback)
    await callback.answer()
    if message is not None:
        await send_shopping(message, callback.from_user.id, session_factory, catalog, settings)


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_shopping, Command("shopping"))
    router.message.register(cmd_shopping, F.text == texts.BTN_NAV_SHOPPING)
    router.callback_query.register(on_shop_button, F.data == "shop:show")
