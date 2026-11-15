"""Logging configuration. Never log personal data or secrets."""

import logging

# These libraries print SQL parameters and request bodies at DEBUG level, which would put a
# person's weight, height or messages into the log. They stay quiet whatever the app level is.
QUIET_LOGGERS = ("aiosqlite", "sqlalchemy.engine", "httpx", "httpcore", "openai")


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging with a single readable format."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
