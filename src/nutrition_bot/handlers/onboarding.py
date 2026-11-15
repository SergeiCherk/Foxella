"""/start and the onboarding questions. Thin: asks, validates the input and calls ``core``."""

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import WELCOME_IMAGE, Settings
from nutrition_bot.core.errors import InvalidProfileError, UnderageError
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.handlers import keyboards
from nutrition_bot.handlers.common import callback_message, low_kcal_note, sender_id, track
from nutrition_bot.handlers.states import Onboarding

logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]
_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:лет|года|год|см|кг)?")
# Free-text steps must not swallow commands or the labels of the permanent panel.
NOT_A_COMMAND = ~F.text.startswith("/") & ~F.text.in_(texts.NAV_LABELS)


def parse_number(text: str) -> float | None:
    """ "64,5 кг" -> 64.5; ``None`` if the text is not a plain number with an optional unit."""
    match = _NUMBER.fullmatch(text.strip().lower())
    return float(match.group(1).replace(",", ".")) if match else None


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value).replace(".", ",")


async def begin_onboarding(message: Message, state: FSMContext) -> None:
    """Ask the first question (also used to edit the profile)."""
    await state.clear()
    await state.set_state(Onboarding.sex)
    await message.answer(texts.ASK_SEX, reply_markup=keyboards.sex_keyboard())


async def send_greeting(message: Message) -> None:
    """The greeting picture with the first words; plain text if the picture cannot be sent."""
    caption = f"{texts.START}\n\n{texts.DISCLAIMER}"
    if WELCOME_IMAGE.is_file():
        try:
            await message.answer_photo(FSInputFile(WELCOME_IMAGE), caption=caption)
            return
        except TelegramAPIError:
            logger.warning("welcome picture could not be sent")
    await message.answer(caption)


async def cmd_start(message: Message, state: FSMContext, session_factory: SessionFactory) -> None:
    """Greet, show the disclaimer and start onboarding for a new person."""
    await state.clear()
    user_id = sender_id(message)
    if user_id is None:
        return
    async with session_factory() as session:
        known = await UserRepository(session).get_profile(user_id) is not None
    await send_greeting(message)
    if known:
        await message.answer(texts.WELCOME_BACK, reply_markup=keyboards.main_keyboard())
    else:
        await begin_onboarding(message, state)


async def on_sex(callback: CallbackQuery, state: FSMContext) -> None:
    """Sex chosen -> ask the age."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    try:
        sex = Sex(callback.data.split(":", 1)[1])
    except ValueError:
        return
    await state.update_data(sex=sex.value)
    await state.set_state(Onboarding.age)
    await message.answer(texts.ASK_AGE)


async def _read_number(
    message: Message, low: float, high: float, example: str
) -> tuple[float | None, bool]:
    """Read a number in [low, high]. Returns (value, ok); on a problem the user was told."""
    value = parse_number(message.text or "")
    if value is None:
        await message.answer(texts.BAD_NUMBER.format(example=example))
        return None, False
    if not low <= value <= high:
        await message.answer(texts.OUT_OF_RANGE.format(low=_fmt(low), high=_fmt(high)))
        return None, False
    return value, True


async def on_age(message: Message, state: FSMContext, settings: Settings) -> None:
    """Age -> refuse politely under 18, otherwise ask the height."""
    cfg = settings.norms
    value = parse_number(message.text or "")
    if value is not None and 1 <= value < cfg.min_age:
        await state.clear()
        await message.answer(texts.UNDERAGE)
        return
    age, ok = await _read_number(message, cfg.min_age, cfg.max_age, "32")
    if not ok or age is None:
        return
    await state.update_data(age=int(age))
    await state.set_state(Onboarding.height)
    await message.answer(texts.ASK_HEIGHT)


async def on_height(message: Message, state: FSMContext, settings: Settings) -> None:
    """Height -> ask the weight."""
    cfg = settings.norms
    height, ok = await _read_number(message, cfg.min_height_cm, cfg.max_height_cm, "168")
    if not ok or height is None:
        return
    await state.update_data(height_cm=height)
    await state.set_state(Onboarding.weight)
    await message.answer(texts.ASK_WEIGHT)


async def on_weight(message: Message, state: FSMContext, settings: Settings) -> None:
    """Weight -> ask the activity level."""
    cfg = settings.norms
    weight, ok = await _read_number(message, cfg.min_weight_kg, cfg.max_weight_kg, "64,5")
    if not ok or weight is None:
        return
    await state.update_data(weight_kg=weight)
    await state.set_state(Onboarding.activity)
    await message.answer(texts.ASK_ACTIVITY, reply_markup=keyboards.activity_keyboard())


async def on_activity(callback: CallbackQuery, state: FSMContext) -> None:
    """Activity chosen -> ask the goal."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    try:
        activity = ActivityLevel(callback.data.split(":", 1)[1])
    except ValueError:
        return
    await state.update_data(activity=activity.value)
    await state.set_state(Onboarding.goal)
    await message.answer(texts.ASK_GOAL, reply_markup=keyboards.goal_keyboard())


async def on_goal(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    """Goal chosen -> compute the norm with the core, save the profile, show the result."""
    message = callback_message(callback)
    await callback.answer()
    if message is None or callback.data is None:
        return
    data = await state.get_data()
    await state.clear()
    try:
        profile = Profile(
            sex=Sex(data["sex"]),
            age=int(data["age"]),
            height_cm=float(data["height_cm"]),
            weight_kg=float(data["weight_kg"]),
            activity=ActivityLevel(data["activity"]),
            goal=Goal(callback.data.split(":", 1)[1]),
        )
        norm = calculate_daily_norm(profile, settings.norms)
    except UnderageError:
        await message.answer(texts.UNDERAGE)
        return
    except (InvalidProfileError, KeyError, ValueError):
        await message.answer(texts.INVALID_PROFILE)
        return
    async with session_factory() as session:
        repo = UserRepository(session)
        is_new = await repo.get_profile(callback.from_user.id) is None
        await repo.save_profile(callback.from_user.id, profile)
        await repo.set_adjustments(callback.from_user.id, [])
    logger.info("profile saved")
    if is_new:  # editing the profile later is not a new onboarding
        await track(session_factory, callback.from_user.id, EventName.ONBOARDING_DONE)
    target = norm.target
    note = low_kcal_note(profile, target.kcal, settings)
    done = texts.ONBOARDING_DONE.format(
        kcal=round(target.kcal),
        protein=round(target.protein_g),
        fat=round(target.fat_g),
        carb=round(target.carb_g),
    )
    await message.answer(texts.NAV_HINT, reply_markup=keyboards.main_keyboard())
    await message.answer(
        done + (f"\n\n{note}" if note else ""),
        reply_markup=keyboards.after_onboarding_keyboard(profile.goal),
    )


def register(router: Router) -> None:
    """Attach this module's handlers to ``router`` (a fresh router for every dispatcher)."""
    router.message.register(cmd_start, CommandStart())
    router.callback_query.register(on_sex, Onboarding.sex, F.data.startswith("sex:"))
    router.message.register(on_age, Onboarding.age, F.text, NOT_A_COMMAND)
    router.message.register(on_height, Onboarding.height, F.text, NOT_A_COMMAND)
    router.message.register(on_weight, Onboarding.weight, F.text, NOT_A_COMMAND)
    router.callback_query.register(on_activity, Onboarding.activity, F.data.startswith("act:"))
    router.callback_query.register(on_goal, Onboarding.goal, F.data.startswith("goal:"))
