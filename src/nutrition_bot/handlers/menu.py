"""/menu: days -> products -> (clarifying questions) -> menu. Thin glue around ``core``."""

import contextlib
import logging
import math
from typing import Any

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.balance import BalanceHint, analyze_day, pantry_hints
from nutrition_bot.core.errors import NutritionError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import (
    DishGenerator,
    MealSource,
    build_menu,
    menu_food_ids,
    staple_food_ids,
)
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import (
    apply_choice,
    callback_message,
    options_of,
    sender_id,
    split_parse,
    track,
)
from nutrition_bot.handlers.guard import MenuGuard
from nutrition_bot.handlers.onboarding import NOT_A_COMMAND
from nutrition_bot.handlers.render import html_text, render_day, render_hints
from nutrition_bot.handlers.states import MenuFlow
from nutrition_bot.services.food_parser import FoodParser

logger = logging.getLogger(__name__)
SessionFactory = async_sessionmaker[AsyncSession]


async def start_menu(
    target: Message,
    user_id: int,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    """Ask how many days to plan (or send the person to /start if there is no profile)."""
    await state.clear()
    async with session_factory() as session:
        profile = await UserRepository(session).get_profile(user_id)
    if profile is None:
        await target.answer(texts.NEED_PROFILE)
        return
    await state.set_state(MenuFlow.days)
    options = list(range(1, settings.menu.max_days + 1))
    await target.answer(texts.MENU_ASK_DAYS, reply_markup=keyboards.days_keyboard(options))


async def cmd_menu(
    message: Message, state: FSMContext, session_factory: SessionFactory, settings: Settings
) -> None:
    """/menu"""
    user_id = sender_id(message)
    if user_id is not None:
        await start_menu(message, user_id, state, session_factory, settings)


async def on_menu_button(
    callback: CallbackQuery, state: FSMContext, session_factory: SessionFactory, settings: Settings
) -> None:
    """The "make a menu" button after onboarding."""
    message = callback_message(callback)
    await callback.answer()
    if message is not None:
        await start_menu(message, callback.from_user.id, state, session_factory, settings)


async def on_days(
    callback: CallbackQuery, state: FSMContext, session_factory: SessionFactory, settings: Settings
) -> None:
    """Days chosen -> ask for the products."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    try:
        days = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    if not 1 <= days <= settings.menu.max_days:
        return
    async with session_factory() as session:
        previous = await UserRepository(session).get_pantry(callback.from_user.id)
    await state.update_data(days=days)
    await state.set_state(MenuFlow.products)
    await message.answer(
        texts.MENU_ASK_PRODUCTS, reply_markup=keyboards.products_keyboard(bool(previous))
    )


async def on_pantry_button(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    catalog: Catalog,
    llm: DishGenerator,
    guard: MenuGuard,
) -> None:
    """ "Any products" or "same as last time"."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    choice = callback.data.split(":", 1)[1]
    pantry: list[int] = []
    if choice == "last":
        async with session_factory() as session:
            pantry = await UserRepository(session).get_pantry(callback.from_user.id)
    await state.update_data(selected=[{"food_id": i} for i in pantry], queue=[])
    await _finish(
        message, callback.from_user.id, state, session_factory, settings, catalog, llm, guard
    )


async def on_products_text(
    message: Message,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    catalog: Catalog,
    llm: DishGenerator,
    guard: MenuGuard,
    parser: FoodParser,
) -> None:
    """Free-text list of products."""
    user_id = sender_id(message)
    if user_id is None:
        return
    result = parser.parse(message.text or "")
    if result.unknown:
        await message.answer(texts.MENU_UNKNOWN_NOTE.format(items=", ".join(result.unknown)))
    sure, questions = split_parse(result)
    if not sure and not questions:
        await message.answer(texts.MENU_PRODUCTS_AGAIN)
        return
    await state.update_data(selected=sure, queue=questions)
    await _next(message, user_id, state, session_factory, settings, catalog, llm, guard)


async def on_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    catalog: Catalog,
    llm: DishGenerator,
    guard: MenuGuard,
) -> None:
    """An answer to a clarifying question."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    data = await state.get_data()
    sure, questions = list(data.get("selected", [])), list(data.get("queue", []))
    try:
        apply_choice(sure, questions, callback.data.split(":", 1)[1])
    except ValueError:
        return
    await state.update_data(selected=sure, queue=questions)
    await _next(
        message, callback.from_user.id, state, session_factory, settings, catalog, llm, guard
    )


async def _next(
    message: Message,
    user_id: int,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    catalog: Catalog,
    llm: DishGenerator,
    guard: MenuGuard,
) -> None:
    """Ask the next question, or build the menu when nothing is left to clarify."""
    data = await state.get_data()
    questions = data.get("queue", [])
    if not questions:
        await _finish(message, user_id, state, session_factory, settings, catalog, llm, guard)
        return
    await state.set_state(MenuFlow.clarify)
    question = questions[0]
    await message.answer(
        texts.MENU_CLARIFY.format(text=question["text"]),
        reply_markup=keyboards.clarify_keyboard(
            "pick", options_of(catalog, question), texts.MENU_CLARIFY_SKIP
        ),
    )


async def _finish(
    message: Message,
    user_id: int,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    catalog: Catalog,
    llm: DishGenerator,
    guard: MenuGuard,
) -> None:
    """Build and send the menu, unless this user is already building one or just finished."""
    verdict = guard.acquire(user_id)
    if not verdict.allowed:
        # The conversation state is kept, so the user can simply try again a bit later.
        if verdict.busy:
            await message.answer(texts.MENU_BUSY)
        else:
            await message.answer(texts.MENU_COOLDOWN.format(seconds=math.ceil(verdict.wait_s)))
        return
    typing = (
        ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id)
        if message.bot is not None
        else contextlib.nullcontext()
    )
    try:
        async with typing:
            await _build_and_send(message, user_id, state, session_factory, settings, catalog, llm)
    finally:
        guard.release(user_id)


async def _build_and_send(
    message: Message,
    user_id: int,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
    catalog: Catalog,
    llm: DishGenerator,
) -> None:
    data: dict[str, Any] = await state.get_data()
    await state.clear()
    pantry = sorted({int(e["food_id"]) for e in data.get("selected", [])})
    days = int(data.get("days", 1))
    async with session_factory() as session:
        repo = UserRepository(session)
        profile = await repo.get_profile(user_id)
        adjustments = await repo.get_adjustments(user_id)
    if profile is None:
        await message.answer(texts.NEED_PROFILE)
        return
    norm = calculate_daily_norm(profile, settings.norms)
    await message.answer(texts.MENU_WORKING)
    try:
        staples = staple_food_ids(catalog, settings.menu.staple_codes)
        allowed = menu_food_ids(catalog, pantry or None, staples)
        results = await build_menu(llm, catalog, norm, days, allowed, settings.menu, adjustments)
    except NutritionError:
        logger.exception("menu could not be built")
        await message.answer(texts.MENU_EMPTY)
        return
    menu = [[r.meal for r in day] for day in results]
    async with session_factory() as session:
        repo = UserRepository(session)
        await repo.set_pantry(user_id, pantry)
        await repo.save_menu(user_id, menu)
        await repo.set_adjustments(user_id, [])

    messages: list[str] = []
    hints: list[BalanceHint] = []
    for number, meals in enumerate(menu, start=1):
        messages += render_day(catalog, number, meals)
        hints += analyze_day(catalog, meals, norm.target, settings.balance)
    if pantry:
        hints += pantry_hints(catalog, pantry, settings.balance)
    notes = [texts.MENU_MEASURE_NOTE]
    if any(r.ignored_availability for day in results for r in day):
        notes.append(texts.MENU_EXTRA_NOTE)
    if any(r.source is MealSource.FALLBACK for day in results for r in day):
        logger.info("some meals came from the built-in dishes")
    hint_block = render_hints(hints)
    closing = [html_text(hint_block)] if hint_block else []
    closing += [f"<i>{html_text(note)}</i>" for note in notes]
    for text in messages:
        await message.answer(text, parse_mode=ParseMode.HTML)
    await message.answer(
        "\n\n".join(closing),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.after_menu_keyboard(),
    )
    await track(session_factory, user_id, EventName.MENU_RECEIVED)


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_menu, Command("menu"))
    router.callback_query.register(on_menu_button, F.data == "menu:start")
    router.callback_query.register(on_days, MenuFlow.days, F.data.startswith("days:"))
    router.callback_query.register(
        on_pantry_button, MenuFlow.products, F.data.startswith("pantry:")
    )
    router.message.register(on_products_text, MenuFlow.products, F.text, NOT_A_COMMAND)
    router.callback_query.register(on_pick, MenuFlow.clarify, F.data.startswith("pick:"))
