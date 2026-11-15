"""Usage events in a real SQLite database."""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.db.models import Base
from nutrition_bot.db.repositories.events import EventRepository
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.db.session import create_engine, create_session_factory

PROFILE = Profile(Sex.MALE, 30, 180.0, 80.0, ActivityLevel.LIGHT, Goal.MAINTAIN)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as db_session:
        yield db_session
    await engine.dispose()


async def test_events_are_stored_in_order_with_utc_times(session: AsyncSession) -> None:
    await UserRepository(session).save_profile(1, PROFILE)
    repo = EventRepository(session)
    await repo.record(1, EventName.ONBOARDING_DONE)
    await repo.record(1, EventName.MENU_RECEIVED)

    events = await repo.all_events()
    assert [e.name for e in events] == [EventName.ONBOARDING_DONE, EventName.MENU_RECEIVED]
    assert all(e.user_id == 1 for e in events)
    assert all(e.at.utcoffset() == timedelta(0) for e in events)  # timezone-aware, UTC
    assert events[0].at <= events[1].at


async def test_an_unknown_user_cannot_have_events(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await EventRepository(session).record(999, EventName.MENU_RECEIVED)


async def test_events_go_away_with_the_user(session: AsyncSession) -> None:
    users = UserRepository(session)
    await users.save_profile(1, PROFILE)
    await users.save_profile(2, PROFILE)
    repo = EventRepository(session)
    await repo.record(1, EventName.MENU_RECEIVED)
    await repo.record(2, EventName.MENU_RECEIVED)

    assert await users.delete_all(1) is True

    assert [e.user_id for e in await repo.all_events()] == [2]


async def test_an_unknown_event_name_is_skipped(session: AsyncSession) -> None:
    await UserRepository(session).save_profile(1, PROFILE)
    repo = EventRepository(session)
    await repo.record(1, EventName.SLIP_PRESSED)
    await session.execute(
        text(
            "INSERT INTO user_events (telegram_id, name, created_at)"
            " VALUES (1, 'from_the_future', '2026-11-15 10:00:00')"
        )
    )
    await session.commit()

    assert [e.name for e in await repo.all_events()] == [EventName.SLIP_PRESSED]
