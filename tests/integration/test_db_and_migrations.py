"""Integration tests: async session factory and Alembic migrations."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from nutrition_bot.db.models import Base
from nutrition_bot.db.session import create_engine, create_session_factory

ROOT = Path(__file__).resolve().parents[2]
CATALOG_TABLES = {"foods", "food_aliases", "measures"}
USER_TABLES = {"users", "user_foods", "user_menus", "user_events"}
ALL_TABLES = CATALOG_TABLES | USER_TABLES


def alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


def table_names(db_file: Path) -> set[str]:
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows} - {"alembic_version"}


async def test_session_executes_query() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    factory = create_session_factory(engine)
    async with factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()


async def test_sqlite_foreign_keys_are_switched_on() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    await engine.dispose()


def test_metadata_contains_all_tables() -> None:
    assert set(Base.metadata.tables) == ALL_TABLES


def test_upgrade_creates_and_downgrade_removes_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    assert table_names(db_file) == ALL_TABLES
    command.downgrade(cfg, "base")
    assert table_names(db_file) == set()
    command.upgrade(cfg, "head")  # and up again: the migration is repeatable
    assert table_names(db_file) == ALL_TABLES


def test_models_and_migration_do_not_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After `upgrade head` Alembic must see no difference to the ORM models."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine as create_sync_engine

    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    command.upgrade(alembic_config(), "head")
    engine = create_sync_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []
