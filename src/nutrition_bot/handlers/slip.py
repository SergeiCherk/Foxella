"""/slip: the person ate something off-plan. Gentle correction spread over the next days."""

import contextlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.eaten import EatenAnalyzer, decompose_eaten
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import meal_targets, menu_food_ids
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.models import DishItem, FoodState, Meal, MealType, Nutrients
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.core.nutrition import day_nutrients, item_nutrients, meal_nutrients
from nutrition_bot.core.slip import (
    eaten_today_kcal,
    menu_day_index,
    merge_adjustments,
    plan_slip_correction,
)
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import (
    Entry,
    answer_remembered,
    apply_choice,
    callback_message,
    options_of,
    remember_choice,
    sender_id,
    split_parse,
    track,
)
from nutrition_bot.handlers.guard import MenuGuard
from nutrition_bot.handlers.onboarding import NOT_A_COMMAND
from nutrition_bot.handlers.render import html_text, render_item_html
from nutrition_bot.handlers.states import SlipFlow
from nutrition_bot.services.food_parser import FoodParser, choose_measure

logger = logging.getLogger(__name__)
SessionFactory = async_sessionmaker[AsyncSession]


def _eaten_item(catalog: Catalog, entry: Entry) -> DishItem | None:
    """What was eaten as a dish item: cooked version of a raw product, the measure named.

    Items the model put together ("measure_id" set) are used as they are.
    """
    food = catalog.get_food(int(entry["food_id"]))
    if "measure_id" in entry:
        measure_id = int(entry["measure_id"])
        if all(m.id != measure_id for m in catalog.measures_for(food.id)):
            return None
        return DishItem(food.id, measure_id, float(entry.get("qty", 1.0)))
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


async def _guess(
    message: Message,
    phrases: list[str],
    catalog: Catalog,
    settings: Settings,
    llm: EatenAnalyzer,
    eaten_guard: MenuGuard,
) -> list[Entry]:
    """Ask the model what unknown phrases are made of; entries for those it could split."""
    user_id = sender_id(message)
    if not phrases or user_id is None or not getattr(llm, "available", True):
        return []
    if not eaten_guard.acquire(user_id).allowed:
        return []  # a short brake on the paid model; the phrases are reported as unknown
    asked = phrases[: settings.slip.llm_max_phrases]
    await message.answer(texts.SLIP_GUESSING.format(items=html_text(", ".join(asked))))
    typing = (
        ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id)
        if message.bot is not None
        else contextlib.nullcontext()
    )
    try:
        async with typing:
            found = await decompose_eaten(
                llm, catalog, asked, menu_food_ids(catalog), settings.menu, settings.slip
            )
    finally:
        eaten_guard.release(user_id)
    return [
        {"food_id": i.food_id, "measure_id": i.measure_id, "qty": i.quantity, "guess": phrase}
        for phrase, items in found.items()
        for i in items
    ]


async def on_slip_text(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    parser: FoodParser,
    settings: Settings,
    llm: EatenAnalyzer,
    eaten_guard: MenuGuard,
    session_factory: SessionFactory,
) -> None:
    """Free text of what was eaten. Food we do not know goes to the model, if there is one."""
    result = parser.parse(message.text or "")
    guessed = await _guess(message, result.unknown, catalog, settings, llm, eaten_guard)
    split = list(dict.fromkeys(e["guess"] for e in guessed))
    unknown = [u for u in result.unknown if u not in split]
    if unknown:
        await message.answer(texts.SLIP_UNKNOWN.format(items=html_text(", ".join(unknown))))
    if split:
        await message.answer(texts.SLIP_GUESSED.format(items=html_text(", ".join(split))))
    sure, questions = split_parse(result)
    sure += guessed
    await answer_remembered(message, session_factory, catalog, sure, questions)
    if not sure and not questions:
        await message.answer(texts.SLIP_NOTHING, reply_markup=keyboards.slip_quick_keyboard())
        return
    await state.update_data(selected=sure, queue=questions)
    await _next(message, state, catalog)


async def on_slip_pick(
    callback: CallbackQuery, state: FSMContext, catalog: Catalog, session_factory: SessionFactory
) -> None:
    """An answer to a clarifying question (a pick of one food is remembered)."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    data = await state.get_data()
    sure, questions = list(data.get("selected", [])), list(data.get("queue", []))
    choice = callback.data.split(":", 1)[1]
    if questions:
        await remember_choice(session_factory, callback.from_user.id, questions[0], choice)
    try:
        apply_choice(sure, questions, choice)
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
    """On top of the plan or instead of a meal -> correct the plan; "redo" -> ask again."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    choice = callback.data.split(":", 1)[1]
    if choice == "redo":
        await state.set_state(SlipFlow.text)
        await message.answer(texts.SLIP_ASK, reply_markup=keyboards.slip_quick_keyboard())
        return
    replaced: MealType | None = None
    if choice.startswith("instead:"):
        try:
            replaced = MealType(choice.removeprefix("instead:"))
        except ValueError:
            return
    elif choice != "yes":
        return
    extra = float((await state.get_data()).get("extra_kcal", 0.0))
    await state.clear()
    await _apply(
        message, callback.from_user.id, extra, session_factory, catalog, settings, replaced
    )


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
    replaced: MealType | None = None,
) -> None:
    """Spread the excess over the next days (core decides) and remember it for the next menu.

    Today's plan is the menu day that falls on today (by the menu's date), else the norm.
    ``replaced``: the food was eaten instead of this meal, so that meal's kcal are taken off.
    A second slip adds to the corrections of the first.
    """
    async with session_factory() as session:
        repo = UserRepository(session)
        profile = await repo.get_profile(user_id)
        menu = await repo.get_menu(user_id)
        created = await repo.get_menu_created_at(user_id)
        existing = await repo.get_adjustments(user_id)
        if profile is None:
            await message.answer(texts.NEED_PROFILE)
            return
        norm = calculate_daily_norm(profile, settings.norms)
        today_plan = None
        if menu and created is not None:
            index = menu_day_index(created.date(), datetime.now(UTC).date(), len(menu))
            today_plan = menu[index] if index is not None else None
        planned = day_nutrients(catalog, today_plan).kcal if today_plan else norm.target.kcal
        replaced_kcal = 0.0
        if replaced is not None:
            replaced_kcal = _meal_kcal(catalog, today_plan, replaced, norm.target, settings)
        days = settings.slip.spread_days
        before = [existing[i] if i < len(existing) else 0.0 for i in range(days)]
        result = plan_slip_correction(
            eaten_kcal=eaten_today_kcal(planned, max(extra_kcal, 0.0), replaced_kcal),
            planned_kcal=planned,
            daily_norm_kcal=norm.target.kcal,
            floor_kcal=norm.floor_kcal,
            upcoming_planned_kcal=[max(0.0, norm.target.kcal + d) for d in before],
            cfg=settings.slip,
            already_cut=[max(0.0, -d) for d in before],
        )
        merged = merge_adjustments(before, result, days)
        await repo.set_adjustments(user_id, merged if any(merged) else [])
    text = texts.SLIP_TEXTS[result.outcome].format(
        excess_kcal=round(result.excess_kcal), per_day_kcal=round(result.average_cut_kcal)
    )
    if replaced is not None:
        note = texts.SLIP_INSTEAD_NOTE.format(
            meal=texts.SLIP_INSTEAD_MEAL[replaced], kcal=round(replaced_kcal)
        )
        text = f"{note}\n\n{text}"
    if not result.adjustments:
        await message.answer(text)
        return
    await message.answer(
        f"{text}\n\n{texts.SLIP_NEXT_MENU}", reply_markup=keyboards.after_onboarding_keyboard()
    )


def _meal_kcal(
    catalog: Catalog,
    day: Sequence[Meal] | None,
    meal_type: MealType,
    target: Nutrients,
    settings: Settings,
) -> float:
    """kcal of a meal in today's plan, else that meal's usual share of the daily target."""
    for meal in day or ():
        if meal.meal_type is meal_type:
            return meal_nutrients(catalog, meal).kcal
    meal_types = [MealType(value) for value in settings.menu.meal_order]
    if meal_type not in meal_types:
        return 0.0
    return meal_targets(target, meal_types, settings.menu)[meal_type].kcal


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_slip, Command("slip"))
    router.message.register(cmd_slip, F.text == texts.BTN_NAV_SLIP)
    router.callback_query.register(on_slip_button, F.data == "slip:start")
    router.message.register(on_slip_text, SlipFlow.text, F.text, NOT_A_COMMAND)
    router.callback_query.register(on_slip_pick, SlipFlow.clarify, F.data.startswith("spick:"))
    router.callback_query.register(on_confirm, SlipFlow.confirm, F.data.startswith("slipc:"))
    router.callback_query.register(on_quick, SlipFlow.text, F.data.startswith("slipq:"))
