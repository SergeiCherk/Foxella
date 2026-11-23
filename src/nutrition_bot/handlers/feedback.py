"""User reviews and complaints forwarded to the configured bot owners."""

import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.handlers import keyboards, menu_cards
from nutrition_bot.handlers.common import callback_message, sender_id
from nutrition_bot.handlers.states import FeedbackFlow

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 3000
_NOT_A_COMMAND = ~F.text.startswith("/") & ~F.text.in_(texts.NAV_LABELS)


async def start_feedback(message: Message, state: FSMContext) -> None:
    """Start choosing the kind of feedback."""
    await state.clear()
    await state.set_state(FeedbackFlow.kind)
    await message.answer(
        f"{texts.FEEDBACK_TITLE}\n\n{texts.FEEDBACK_CHOOSE}",
        reply_markup=keyboards.feedback_keyboard(),
    )


async def cmd_feedback(message: Message, state: FSMContext) -> None:
    """The /feedback command."""
    await start_feedback(message, state)


async def on_feedback_button(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if (message := callback_message(callback)) is not None:
        await start_feedback(message, state)


async def on_report(
    callback: CallbackQuery, state: FSMContext, session_factory: menu_cards.SessionFactory
) -> None:
    message = callback_message(callback)
    parts = (callback.data or "").split(":")
    saved = (
        await menu_cards.load_card(session_factory, callback.from_user.id, parts[:-1])
        if message is not None and len(parts) == 5
        else None
    )
    if message is None or saved is None or (index := saved[3]) is None:
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    days, _, day, _ = saved
    dish = [dish for meal in days[day] for dish in meal.dishes][index]
    await state.clear()
    await state.set_data({"kind": "complaint", "dish_context": f"День {day + 1}: {dish.name}"})
    await state.set_state(FeedbackFlow.text)
    await message.answer(
        texts.FEEDBACK_ASK_COMPLAINT, reply_markup=keyboards.feedback_cancel_keyboard()
    )


async def on_kind(callback: CallbackQuery, state: FSMContext) -> None:
    """Choose review or complaint and ask for its text."""
    await callback.answer()
    message = callback_message(callback)
    if message is None or callback.data is None:
        return
    kind = callback.data.split(":", 1)[1]
    if kind not in {"review", "complaint"}:
        return
    await state.update_data(kind=kind)
    await state.set_state(FeedbackFlow.text)
    prompt = texts.FEEDBACK_ASK_REVIEW if kind == "review" else texts.FEEDBACK_ASK_COMPLAINT
    await message.answer(prompt, reply_markup=keyboards.feedback_cancel_keyboard())


async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel feedback from either step."""
    await callback.answer()
    await state.clear()
    message = callback_message(callback)
    if message is not None:
        await message.answer(texts.FEEDBACK_CANCELLED)


async def on_text(message: Message, state: FSMContext, settings: Settings) -> None:
    """Forward the entered text to every configured owner."""
    text = (message.text or "").strip()
    if not text:
        return
    if len(text) > _MAX_MESSAGE_LENGTH:
        await message.answer(
            texts.FEEDBACK_TOO_LONG,
            reply_markup=keyboards.feedback_cancel_keyboard(),
        )
        return
    user_id = sender_id(message)
    bot = message.bot
    if user_id is None or bot is None or not settings.admin_ids:
        await state.clear()
        await message.answer(texts.FEEDBACK_UNAVAILABLE)
        return
    data = await state.get_data()
    kind = data.get("kind")
    if kind not in {"review", "complaint"}:
        await state.clear()
        await message.answer(texts.FEEDBACK_UNAVAILABLE)
        return
    template = texts.FEEDBACK_ADMIN_REVIEW if kind == "review" else texts.FEEDBACK_ADMIN_COMPLAINT
    context = data.get("dish_context")
    body = f"{context}\n\n{text}" if isinstance(context, str) else text
    admin_text = template.format(user_id=user_id, text=escape(body, quote=False))
    delivered = False
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except TelegramAPIError:
            logger.warning("could not deliver feedback to an admin")
        else:
            delivered = True
    await state.clear()
    await message.answer(texts.FEEDBACK_SENT if delivered else texts.FEEDBACK_UNAVAILABLE)


def register(router: Router) -> None:
    """Attach feedback handlers to the application router."""
    router.message.register(cmd_feedback, Command("feedback"))
    router.message.register(cmd_feedback, F.text == texts.BTN_NAV_FEEDBACK)  # legacy keyboards
    router.callback_query.register(on_feedback_button, F.data == "feedback:open")
    router.callback_query.register(
        on_report, F.data.startswith("plan:") & F.data.endswith(":report")
    )
    router.callback_query.register(on_cancel, FeedbackFlow.kind, F.data == "feedback:cancel")
    router.callback_query.register(on_cancel, FeedbackFlow.text, F.data == "feedback:cancel")
    router.callback_query.register(on_kind, FeedbackFlow.kind, F.data.startswith("feedback:"))
    router.message.register(on_text, FeedbackFlow.text, F.text, _NOT_A_COMMAND)
