"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest

from nutrition_bot.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Make sure every test sees fresh settings."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    """Settings that never read a real .env file or secrets."""
    return Settings(_env_file=None, bot_token="", llm_api_key="")  # type: ignore[call-arg]
