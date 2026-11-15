"""Entry point: ``python -m nutrition_bot``."""

import asyncio
import logging

from nutrition_bot.bot import run
from nutrition_bot.config import get_settings
from nutrition_bot.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Load settings, configure logging and start the bot."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Foxella bot")
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
