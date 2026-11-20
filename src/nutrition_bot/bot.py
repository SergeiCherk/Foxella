"""Assembly of the aiogram Bot and Dispatcher (kept separate from ``__main__`` for tests)."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.config import PROJECT_ROOT, Settings
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import DishGenerator
from nutrition_bot.core.recipe_check import MentionFinder
from nutrition_bot.db.repositories.foods import FoodRepository
from nutrition_bot.db.seed import load_foods, load_measures
from nutrition_bot.db.session import create_engine, create_session_factory
from nutrition_bot.handlers import build_router
from nutrition_bot.handlers.guard import MenuGuard
from nutrition_bot.services.food_parser import FoodParser
from nutrition_bot.services.llm import build_llm
from nutrition_bot.services.recipe_mentions import AliasMentionFinder

logger = logging.getLogger(__name__)


def build_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    catalog: Catalog,
    llm: DishGenerator,
    parser: FoodParser,
    guard: MenuGuard | None = None,
    mentions: MentionFinder | None = None,
    eaten_guard: MenuGuard | None = None,
) -> Dispatcher:
    """Create the dispatcher; its keyword arguments are what handlers receive by name.

    ``mentions`` finds foods in the model's recipe texts (hidden calories, amounts); without it
    recipes get only the plain text checks. ``eaten_guard`` limits how often one person's
    unknown food is sent to the model in "I ate".
    """
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        settings=settings,
        session_factory=session_factory,
        catalog=catalog,
        llm=llm,
        parser=parser,
        guard=guard or MenuGuard(settings.menu.cooldown_s),
        mentions=mentions,
        eaten_guard=eaten_guard or MenuGuard(settings.slip.llm_cooldown_s),
    )
    dispatcher.include_router(build_router())
    return dispatcher


def create_bot(token: str, session: Any = None) -> Bot:
    """The Telegram bot. Every message is Telegram HTML: texts use <b>, <i> and <blockquote>,
    and anything a person typed or a language model wrote is escaped before it is inserted."""
    default = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    if session is None:
        return Bot(token=token, default=default)
    return Bot(token=token, default=default, session=session)


def migrate(root: Path = PROJECT_ROOT) -> None:
    """Bring the database schema to the latest version (blocking; run it in a thread)."""
    cfg = Config(str(root / "alembic.ini"), attributes={"configure_logger": False})
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


async def run(settings: Settings) -> None:
    """Prepare the database, then start long polling. Fails early if the token is missing."""
    token = settings.bot_token.get_secret_value()
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    await asyncio.to_thread(migrate)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        repo = FoodRepository(session)
        await repo.seed(load_foods(), load_measures())
        catalog = await repo.load_catalog()
        aliases = await repo.load_aliases()
    parser = FoodParser(aliases, settings.parser)
    llm = build_llm(settings, catalog)
    bot = create_bot(token)
    dispatcher = build_dispatcher(
        settings, session_factory, catalog, llm, parser, mentions=AliasMentionFinder(aliases)
    )
    try:
        # Inside the try block: if Telegram is unreachable here, the session is still closed.
        await bot.set_my_commands(
            [BotCommand(command=c, description=d) for c, d in texts.BOT_COMMANDS.items()]
        )
        logger.info("Polling started")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
