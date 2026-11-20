"""Conversation state (aiogram FSM) in our database, so a restart does not strand anyone.

``MemoryStorage`` loses every half-finished conversation when the bot restarts: a person in the
middle of the questionnaire or the menu flow would press buttons that no longer lead anywhere.
This storage keeps the state and its data in the ``fsm_states`` table.

Privacy: the data can hold what the person typed ("творог, курица") while a conversation is
going on. A finished conversation (state and data cleared) removes its row at once, and rows
older than ``ttl`` are ignored and deleted, so nothing typed is kept for long.
"""

import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StateType, StorageKey
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot.db.models import FsmStateORM

logger = logging.getLogger(__name__)

DEFAULT_TTL = timedelta(hours=24)  # ASSUMPTION: an unfinished conversation is kept for a day
PURGE_EVERY_S = 3600.0  # expired rows are deleted at most once an hour


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlStorage(BaseStorage):
    """aiogram FSM storage on top of the bot's SQLAlchemy database (one row per chat and user)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ttl: timedelta = DEFAULT_TTL,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl
        self._now = now
        self._keys = DefaultKeyBuilder(with_bot_id=True, with_destiny=True)
        self._purged_at = float("-inf")

    async def _row(self, session: AsyncSession, key: StorageKey) -> FsmStateORM | None:
        row = await session.get(FsmStateORM, self._keys.build(key))
        if row is not None and _aware(row.updated_at) < self._now() - self._ttl:
            await session.delete(row)
            return None
        return row

    async def _save(self, key: StorageKey, state: str | None, data: Mapping[str, Any]) -> None:
        async with self._session_factory() as session:
            row = await session.get(FsmStateORM, self._keys.build(key))
            if state is None and not data:
                if row is not None:
                    await session.delete(row)  # the conversation is over: forget it
            else:
                if row is None:
                    row = FsmStateORM(key=self._keys.build(key), user_id=key.user_id)
                    session.add(row)
                row.state = state
                row.data = json.dumps(dict(data), ensure_ascii=False)
                row.updated_at = self._now()
            await session.commit()
        await self._purge_expired()

    async def _purge_expired(self) -> None:
        if time.monotonic() - self._purged_at < PURGE_EVERY_S:
            return
        self._purged_at = time.monotonic()
        async with self._session_factory() as session:
            cutoff = self._now() - self._ttl
            await session.execute(delete(FsmStateORM).where(FsmStateORM.updated_at < cutoff))
            await session.commit()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        """Set or clear the state; the data stays as it was."""
        value = state.state if isinstance(state, State) else state
        async with self._session_factory() as session:
            row = await self._row(session, key)
            data = json.loads(row.data) if row is not None else {}
        await self._save(key, value, data)

    async def get_state(self, key: StorageKey) -> str | None:
        """The current state, ``None`` if there is none or it expired."""
        async with self._session_factory() as session:
            row = await self._row(session, key)
            await session.commit()
            return None if row is None else row.state

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        """Replace the data; the state stays as it was."""
        async with self._session_factory() as session:
            row = await self._row(session, key)
            state = row.state if row is not None else None
        await self._save(key, state, data)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        """The current data, empty if there is none, it expired or cannot be read."""
        async with self._session_factory() as session:
            row = await self._row(session, key)
            await session.commit()
            if row is None:
                return {}
            try:
                data = json.loads(row.data)
            except ValueError:
                logger.warning("unreadable conversation data, starting afresh")
                return {}
            return data if isinstance(data, dict) else {}

    async def close(self) -> None:
        """Nothing to close: the engine belongs to the bot."""

    async def count(self) -> int:
        """Number of stored conversations (for tests and diagnostics)."""
        async with self._session_factory() as session:
            return len((await session.scalars(select(FsmStateORM.key))).all())
