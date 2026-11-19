"""/slip: the person ate something off-plan. Gentle correction spread over the next days."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import menu_food_ids
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.models import DishItem, FoodState
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.core.nutrition import day_nutrients, item_nutrients
from nutrition_bot.core.slip import plan_slip_correction
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import (
    Entry,
    apply_choice,
    callback_message,
    options_of,
    sender_id,
    split_parse,
    track,
)
from nutrition_bot.handlers.onboarding import NOT_A_COMMAND
from nutrition_bot.handlers.render import html_text, render_item_html
from nutrition_bot.handlers.states import SlipFlow
from nutrition_bot.services.food_parser import FoodParser, choose_measure

logger = logging.getLogger(__name__)
SessionFactory = async_sessionmaker[AsyncSession]


def _eaten_item(catalog: Catalog, entry: Entry) -> DishItem | None:
    """What was eaten as a dish item: cooked version of a raw product, the measure named."""
    food = catalog.get_food(int(entry["food_id"]))
    if food.state is FoodState.RAW:
        cooked = menu_food_ids(catalog, [food.id])
        food = catalog.get_food(cooked[0]) if cooked else food
    measure = choose_measure(catalog.measures_for(food.id), frozenset(entry.get("words", [])))
    if measure is None:
        return None
    return DishItem(food.id, measure.id, float(entry.get("qty", 1.0)))


async def start_slip(
    target: Message,
    user_id: int,
    state: FSMContext,
    session_factory: SessionFactory,
) -> None:
    """Ask what was eaten (or send the person to /start if there is no profile)."""
    await state.clear()
    async with session_factory() as session:
        profile = await UserRepository(session).get_profile(user_id)
    if profile is None:
        await target.answer(texts.NEED_PROFILE)
        return
    await track(session_factory, user_id, EventName.SLIP_PRESSED)
    await state.set_state(SlipFlow.text)
    await target.answer(texts.SLIP_ASK, reply_markup=keyboards.slip_quick_keyboard())


async def cmd_slip(message: Message, state: FSMContext, session_factory: SessionFactory) -> None:
    """/slip"""
    user_id = sender_id(message)
    if user_id is not None:
        await start_slip(message, user_id, state, session_factory)


async def on_slip_button(
    callback: CallbackQuery, state: FSMContext, session_factory: SessionFactory
) -> None:
    """The "ate something else" button under a menu."""
    message = callback_message(callback)
    await callback.answer()
    if message is not None:
        await start_slip(message, callback.from_user.id, state, session_factory)


async def on_slip_text(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    parser: FoodParser,
) -> None:
    """Free text of what was eaten."""
    result = parser.parse(message.text or "")
    if result.unknown:
        await message.answer(texts.SLIP_UNKNOWN.format(items=html_text(", ".join(result.unknown))))
    sure, questions = split_parse(result)
    if not sure and not questions:
        await message.answer(texts.SLIP_NOTHING, reply_markup=keyboards.slip_quick_keyboard())
        return
    await state.update_data(selected=sure, queue=questions)
    await _next(message, state, catalog)


async def on_slip_pick(callback: CallbackQuery, state: FSMContext, catalog: Catalog) -> None:
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
    await _next(message, state, catalog)


async def _next(message: Message, state: FSMContext, catalog: Catalog) -> None:
    """Ask the next question, or show what was understood and ask for confirmation."""
    data = await state.get_data()
    questions = data.get("queue", [])
    if questions:
        await state.set_state(SlipFlow.clarify)
        await message.answer(
            texts.MENU_CLARIFY.format(text=html_text(questions[0]["text"])),
            reply_markup=keyboards.clarify_keyboard(
                "spick", options_of(catalog, questions[0]), texts.MENU_CLARIFY_SKIP
            ),
        )
        return
    items = [i for e in data.get("selected", []) if (i := _eaten_item(catalog, e)) is not None]
    if not items:
        await state.set_state(SlipFlow.text)
        await message.answer(texts.SLIP_NOTHING, reply_markup=keyboards.slip_quick_keyboard())
        return
    kcal = sum(item_nutrients(catalog, i).kcal for i in items)
    await state.update_data(extra_kcal=kcal)
    await state.set_state(SlipFlow.confirm)
    await message.answer(
        texts.SLIP_CONFIRM.format(
            lines="\n".join(render_item_html(catalog, i) for i in items), kcal=round(kcal)
        ),
        reply_markup=keyboards.slip_confirm_keyboard(),
    )


async def on_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: SessionFactory,
    catalog: Catalog,
    settings: Settings,
) -> None:
    """Confirmed -> correct the plan; "redo" -> ask again."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    if callback.data.endswith("redo"):
        await state.set_state(SlipFlow.text)
        await message.answer(texts.SLIP_ASK, reply_markup=keyboards.slip_quick_keyboard())
        return
    extra = float((await state.get_data()).get("extra_kcal", 0.0))
    await state.clear()
    await _apply(message, callback.from_user.id, extra, session_factory, catalog, settings)


async def on_quick(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: SessionFactory,
    catalog: Catalog,
    settings: Settings,
) -> None:
    """A rough size instead of a list of foods."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    extra = settings.slip.quick_kcal.get(callback.data.split(":", 1)[1])
    if extra is None:
        return
    await state.clear()
    await _apply(message, callback.from_user.id, extra, session_factory, catalog, settings)


async def _apply(
    message: Message,
    user_id: int,
    extra_kcal: float,
    session_factory: SessionFactory,
    catalog: Catalog,
    settings: Settings,
) -> None:
    """Spread the excess over the next days (core decides) and remember it for the next menu."""
    async with session_factory() as session:
        repo = UserRepository(session)
        profile = await repo.get_profile(user_id)
        menu = await repo.get_menu(user_id)
        if profile is None:
            await message.answer(texts.NEED_PROFILE)
            return
        norm = calculate_daily_norm(profile, settings.norms)
        planned = day_nutrients(catalog, menu[0]).kcal if menu else norm.target.kcal
        days = settings.slip.spread_days
        result = plan_slip_correction(
            eaten_kcal=planned + max(extra_kcal, 0.0),
            planned_kcal=planned,
            daily_norm_kcal=norm.target.kcal,
            floor_kcal=norm.floor_kcal,
            upcoming_planned_kcal=[norm.target.kcal] * days,
            cfg=settings.slip,
        )
        deltas = [0.0] * days
        for adjustment in result.adjustments:
            deltas[adjustment.day_offset] = adjustment.delta_kcal
        await repo.set_adjustments(user_id, deltas if result.adjustments else [])
    text = texts.SLIP_TEXTS[result.outcome].format(
        excess_kcal=round(result.excess_kcal), per_day_kcal=round(result.average_cut_kcal)
    )
    if not result.adjustments:
        await message.answer(text)
        return
    await message.answer(
        f"{text}\n\n{texts.SLIP_NEXT_MENU}", reply_markup=keyboards.after_onboarding_keyboard()
    )


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_slip, Command("slip"))
    router.message.register(cmd_slip, F.text == texts.BTN_NAV_SLIP)
    router.callback_query.register(on_slip_button, F.data == "slip:start")
    router.message.register(on_slip_text, SlipFlow.text, F.text, NOT_A_COMMAND)
    router.callback_query.register(on_slip_pick, SlipFlow.clarify, F.data.startswith("spick:"))
    router.callback_query.register(on_confirm, SlipFlow.confirm, F.data.startswith("slipc:"))
    router.callback_query.register(on_quick, SlipFlow.text, F.data.startswith("slipq:"))
