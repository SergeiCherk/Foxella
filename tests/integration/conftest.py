"""Fixtures for tests that need the database and the bot."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path

import pytest

from nutrition_bot.config import Settings
from nutrition_bot.core.menu import DishGenerator
from nutrition_bot.handlers.guard import MenuGuard
from tests.integration.app_builder import bot_app
from tests.integration.bot_harness import BotHarness

AppFactory = Callable[..., Awaitable[BotHarness]]


@pytest.fixture
async def make_app(tmp_path: Path, settings: Settings) -> AsyncIterator[AppFactory]:
    """Build bots on fresh SQLite files seeded with the real food data (own LLM and guard)."""
    async with AsyncExitStack() as stack:
        count = 0

        async def factory(
            llm: DishGenerator | None = None,
            guard: MenuGuard | None = None,
            use: Settings | None = None,
        ) -> BotHarness:
            nonlocal count
            count += 1
            return await stack.enter_async_context(
                bot_app(tmp_path / f"bot{count}.db", use or settings, llm, guard)
            )

        yield factory


@pytest.fixture
async def app(make_app: AppFactory) -> BotHarness:
    """A bot whose LLM always fails and that has no pause between menus.

    A failing LLM means every meal comes from the built-in dishes, so the tests are fast and
    deterministic and still exercise the whole menu path. The anti-spam pause is switched off
    here; ``test_protection.py`` tests it with a real pause.
    """
    return await make_app()
