"""Telegram layer: routers for each conversation. Handlers stay thin and call ``core``."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from nutrition_bot import texts
from nutrition_bot.handlers import goal, menu, onboarding, profile, restrictions, shopping, slip

logger = logging.getLogger(__name__)


def build_router() -> Router:
    """All routers in the order that matters: commands and state steps first, fallback last."""
    root = Router(name="root")
    # A router's own handlers run before those of the routers included in it, so the catch-all
    # lives in a router of its own that is included last.
    for module in (onboarding, profile, restrictions, goal, menu, shopping, slip):
        child = Router(name=module.__name__.rsplit(".", 1)[-1])
        module.register(child)
        root.include_router(child)
    last = Router(name="fallback")
    last.message.register(fallback, F.text)
    last.callback_query.register(stale_button)
    root.include_router(last)
    root.errors.register(on_error)
    return root


async def fallback(message: Message, state: FSMContext) -> None:
    """Any text that no conversation step expects."""
    await state.clear()
    await message.answer(texts.FALLBACK)


async def stale_button(callback: CallbackQuery) -> None:
    """A button that no step expects (old message, restarted bot): say so instead of spinning."""
    await callback.answer(texts.STALE_BUTTON)


async def on_error(event: ErrorEvent) -> bool:
    """Log the failure (type only, never the user's text) and apologise instead of crashing."""
    logger.error("handler failed: %s", type(event.exception).__name__, exc_info=event.exception)
    update = event.update
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if isinstance(target, Message):
        await target.answer(texts.ERROR_GENERIC)
    return True
