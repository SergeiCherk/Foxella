"""Builds a bot on a fresh SQLite file with the real food data and a mocked Telegram session."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from nutrition_bot.bot import build_dispatcher, create_bot
from nutrition_bot.config import Settings
from nutrition_bot.core.menu import DishGenerator
from nutrition_bot.db.models import Base
from nutrition_bot.db.repositories.foods import FoodRepository
from nutrition_bot.db.seed import load_foods, load_measures
from nutrition_bot.db.session import create_engine, create_session_factory
from nutrition_bot.handlers.guard import MenuGuard
from nutrition_bot.services.food_parser import FoodParser
from nutrition_bot.services.llm import FakeLLM
from nutrition_bot.services.recipe_mentions import AliasMentionFinder
from tests.integration.bot_harness import BotHarness, MockedSession


@asynccontextmanager
async def bot_app(
    database_file: Path,
    settings: Settings,
    llm: DishGenerator | None = None,
    guard: MenuGuard | None = None,
) -> AsyncIterator[BotHarness]:
    """Yield a ready bot; the database connection is closed when the block ends.

    Without ``llm`` the bot uses ``FakeLLM``, which always fails, so every meal comes from the
    built-in dishes. Without ``guard`` there is no pause between menus.
    """
    engine = create_engine(f"sqlite+aiosqlite:///{database_file.as_posix()}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repo = FoodRepository(session)
            await repo.seed(load_foods(), load_measures())
            catalog = await repo.load_catalog()
            aliases = await repo.load_aliases()
        dispatcher = build_dispatcher(
            settings,
            session_factory,
            catalog,
            llm or FakeLLM(),
            FoodParser(aliases, settings.parser),
            guard=guard or MenuGuard(0.0),
            mentions=AliasMentionFinder(aliases),
        )
        bot = create_bot("123456:TEST-TOKEN", session=MockedSession())
        yield BotHarness(dispatcher, bot, session_factory, catalog)
    finally:
        await engine.dispose()
