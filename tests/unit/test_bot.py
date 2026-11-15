"""Tests for bot assembly, startup and the entry point."""

import logging
from pathlib import Path
from typing import Any

import pytest
from aiogram import Dispatcher

from nutrition_bot import __main__ as entry
from nutrition_bot import bot as bot_module
from nutrition_bot.bot import build_dispatcher, migrate, run
from nutrition_bot.config import Settings
from nutrition_bot.core.measures import Catalog
from nutrition_bot.logging_setup import QUIET_LOGGERS, setup_logging
from nutrition_bot.services.food_parser import FoodParser
from nutrition_bot.services.llm import FakeLLM


def make_dispatcher(settings: Settings) -> Dispatcher:
    return build_dispatcher(
        settings, None, Catalog([], []), FakeLLM(), FoodParser({}, settings.parser)
    )  # type: ignore[arg-type]


def test_build_dispatcher_returns_dispatcher(settings: Settings) -> None:
    assert isinstance(make_dispatcher(settings), Dispatcher)


def test_dispatcher_can_be_built_many_times(settings: Settings) -> None:
    """Every call needs its own routers (a router can be attached only once)."""
    assert make_dispatcher(settings) is not make_dispatcher(settings)


def test_dispatcher_passes_dependencies_to_handlers(settings: Settings) -> None:
    data = make_dispatcher(settings).workflow_data
    assert {"settings", "session_factory", "catalog", "llm", "parser"} <= set(data)


async def test_run_without_token_exits_with_clear_message(settings: Settings) -> None:
    with pytest.raises(SystemExit) as exc:
        await run(settings)
    assert "BOT_TOKEN" in str(exc.value)


async def test_run_prepares_everything_then_polls_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'run.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    class FakeBot:
        def __init__(self, token: str) -> None:
            calls.append(f"bot:{token}")
            self.session = self

        async def set_my_commands(self, commands: list[Any]) -> None:
            calls.append(f"commands:{len(commands)}")

        async def close(self) -> None:
            calls.append("closed")

    async def fake_polling(self: Dispatcher, bot: FakeBot) -> None:
        calls.append("polling")

    monkeypatch.setattr(bot_module, "Bot", FakeBot)
    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)
    settings = Settings(_env_file=None, bot_token="123:abc", database_url=db_url)  # type: ignore[call-arg]
    await run(settings)
    assert calls == ["bot:123:abc", "commands:6", "polling", "closed"]
    assert (tmp_path / "run.db").exists()


async def test_run_cleans_up_when_telegram_is_unreachable_at_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'down.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    class DownBot:
        def __init__(self, token: str) -> None:
            self.session = self

        async def set_my_commands(self, commands: list[Any]) -> None:
            raise ConnectionError("Telegram is unreachable")

        async def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(bot_module, "Bot", DownBot)
    settings = Settings(_env_file=None, bot_token="123:abc", database_url=db_url)  # type: ignore[call-arg]
    with pytest.raises(ConnectionError):
        await run(settings)
    assert calls == ["closed"]  # the HTTP session is not left open
    assert (tmp_path / "down.db").exists()  # the database was prepared before the failure


def test_migrate_creates_the_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    migrate()
    migrate()  # running it again on an up-to-date database is harmless
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"foods", "users", "user_foods", "user_menus", "user_events"} <= tables


def test_setup_logging_does_not_raise() -> None:
    setup_logging("DEBUG")
    assert logging.getLogger().level in (logging.DEBUG, logging.NOTSET, logging.WARNING)


def test_noisy_libraries_stay_quiet_even_in_debug() -> None:
    setup_logging("DEBUG")
    for name in QUIET_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_main_starts_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def fake_run(_settings: Settings) -> None:
        called.append("run")

    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setattr(entry, "run", fake_run)
    entry.main()
    assert called == ["run"]


def test_migrations_do_not_switch_off_the_application_loggers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alembic's logging setup used to disable every logger created before it ran."""
    probe = logging.getLogger("nutrition_bot.probe")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'l.db').as_posix()}")
    migrate()
    assert probe.disabled is False
