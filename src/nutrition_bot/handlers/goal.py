"""Optional check of a target weight and term: is the pace safe? Nothing is stored."""

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.errors import InvalidProfileError, UnrealisticGoalError
from nutrition_bot.core.models import Goal
from nutrition_bot.core.norms import check_weight_goal
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import callback_message, sender_id
from nutrition_bot.handlers.onboarding import NOT_A_COMMAND, parse_number
from nutrition_bot.handlers.states import GoalCheck

SessionFactory = async_sessionmaker[AsyncSession]
WEEK_OPTIONS = (4, 8, 12, 24)
_WEEKS = re.compile(r"(\d{1,4})\s*(?:нед(?:ель|ели|еля|\.)?|н)?")


def _kg(value: float) -> str:
    """0.5 -> "0,5", 0.25 -> "0,25"."""
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def parse_weeks(text: str) -> int | None:
    """ "12" or "12 недель" -> 12; ``None`` if it is not a whole number of weeks."""
    match = _WEEKS.fullmatch(text.strip().lower())
    return int(match.group(1)) if match else None


async def on_start(
    callback: CallbackQuery, state: FSMContext, session_factory: SessionFactory
) -> None:
    """The "check my term" button: ask for the target weight."""
    message = callback_message(callback)
    await callback.answer()
    if message is None:
        return
    await state.clear()
    async with session_factory() as session:
        profile = await UserRepository(session).get_profile(callback.from_user.id)
    if profile is None:
        await message.answer(texts.NEED_PROFILE)
        return
    if profile.goal is Goal.MAINTAIN:
        await message.answer(texts.GOAL_NOT_NEEDED)
        return
    await state.set_state(GoalCheck.target)
    weight = f"{profile.weight_kg:g}".replace(".", ",")
    await message.answer(texts.GOAL_ASK_TARGET.format(weight=weight))


async def on_target(message: Message, state: FSMContext) -> None:
    """The target weight was typed."""
    value = parse_number(message.text or "")
    if value is None:
        await message.answer(texts.GOAL_NOT_A_NUMBER)
        return
    await state.update_data(target=value)
    await state.set_state(GoalCheck.weeks)
    await message.answer(texts.GOAL_ASK_WEEKS, reply_markup=keyboards.weeks_keyboard(WEEK_OPTIONS))


async def on_weeks_button(
    callback: CallbackQuery, state: FSMContext, session_factory: SessionFactory, settings: Settings
) -> None:
    """A term was chosen with a button."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    weeks = parse_weeks(callback.data.split(":", 1)[1])
    if weeks is not None:
        await _check(message, callback.from_user.id, weeks, state, session_factory, settings)


async def on_weeks_text(
    message: Message, state: FSMContext, session_factory: SessionFactory, settings: Settings
) -> None:
    """A term was typed."""
    user_id = sender_id(message)
    weeks = parse_weeks(message.text or "")
    if user_id is None:
        return
    if weeks is None:
        await message.answer(texts.GOAL_BAD_WEEKS.format(max_weeks=settings.norms.max_goal_weeks))
        return
    await _check(message, user_id, weeks, state, session_factory, settings)


async def _check(
    message: Message,
    user_id: int,
    weeks: int,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    data = await state.get_data()
    target = data.get("target")
    async with session_factory() as session:
        profile = await UserRepository(session).get_profile(user_id)
    if profile is None or not isinstance(target, int | float):
        await state.clear()
        await message.answer(texts.NEED_PROFILE)
        return
    try:
        pace = check_weight_goal(profile, float(target), weeks, settings.norms)
    except UnrealisticGoalError as error:
        await state.clear()
        if error.min_safe_weeks is None:
            await message.answer(texts.GOAL_NO_SAFE)
            return
        await message.answer(
            texts.GOAL_TOO_FAST.format(
                weeks_asked=weeks,
                pace_asked=_kg(error.requested_weekly_kg),
                safe=_kg(error.safe_weekly_kg),
                weeks=error.min_safe_weeks,
            )
        )
        return
    except InvalidProfileError as error:
        if error.field == "weeks":
            await message.answer(
                texts.GOAL_BAD_WEEKS.format(max_weeks=settings.norms.max_goal_weeks),
                reply_markup=keyboards.weeks_keyboard(WEEK_OPTIONS),
            )
            return
        # the target weight itself is wrong: ask for it again
        await state.set_state(GoalCheck.target)
        await message.answer(texts.GOAL_BAD_TARGET)
        return
    await state.clear()
    await message.answer(texts.GOAL_OK.format(pace=_kg(pace)))


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.callback_query.register(on_start, F.data == "goalcheck:start")
    router.message.register(on_target, GoalCheck.target, F.text, NOT_A_COMMAND)
    router.callback_query.register(on_weeks_button, GoalCheck.weeks, F.data.startswith("weeks:"))
    router.message.register(on_weeks_text, GoalCheck.weeks, F.text, NOT_A_COMMAND)
