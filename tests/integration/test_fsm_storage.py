"""Conversations in the database (db.fsm_storage): they survive a restart and do not linger."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import update

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.db.fsm_storage import SqlStorage
from nutrition_bot.db.models import Base, FsmStateORM
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.db.session import create_engine, create_session_factory
from tests.integration.app_builder import bot_app


class Flow(StatesGroup):
    step = State()


KEY = StorageKey(bot_id=1, chat_id=10, user_id=10)
OTHER = StorageKey(bot_id=1, chat_id=11, user_id=11)


async def storage(tmp_path: Path, **kw: object) -> SqlStorage:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'fsm.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return SqlStorage(create_session_factory(engine), **kw)  # type: ignore[arg-type]


async def test_state_and_data_are_kept_separately_per_person(tmp_path: Path) -> None:
    fsm = await storage(tmp_path)
    await fsm.set_state(KEY, Flow.step)
    await fsm.update_data(KEY, {"days": 3, "selected": [{"food_id": 6, "words": ["тарелка"]}]})
    assert await fsm.get_state(KEY) == "Flow:step"
    assert await fsm.get_data(KEY) == {
        "days": 3,
        "selected": [{"food_id": 6, "words": ["тарелка"]}],
    }
    assert await fsm.get_state(OTHER) is None
    assert await fsm.get_data(OTHER) == {}
    await fsm.set_data(KEY, {"days": 1})
    assert await fsm.get_state(KEY) == "Flow:step"  # data alone does not touch the state


async def test_a_finished_conversation_leaves_no_row(tmp_path: Path) -> None:
    fsm = await storage(tmp_path)
    await fsm.set_state(KEY, "Flow:step")
    await fsm.set_data(KEY, {"text": "творог"})
    await fsm.set_state(KEY, None)
    assert await fsm.count() == 1  # the data is still there
    await fsm.set_data(KEY, {})
    assert await fsm.count() == 0
    await fsm.set_data(OTHER, {})  # clearing what does not exist is fine
    assert await fsm.count() == 0
    await fsm.close()


async def test_old_conversations_are_forgotten(tmp_path: Path) -> None:
    clock = [datetime(2026, 11, 20, 12, tzinfo=UTC)]
    fsm = await storage(tmp_path, ttl=timedelta(hours=24), now=lambda: clock[0])
    await fsm.set_state(KEY, "Flow:step")
    await fsm.set_data(OTHER, {"text": "курица"})
    clock[0] += timedelta(hours=25)
    assert await fsm.get_state(KEY) is None
    assert await fsm.get_data(OTHER) == {}
    assert await fsm.count() == 0  # read as expired, and removed


async def test_expired_rows_of_people_who_never_came_back_are_purged(tmp_path: Path) -> None:
    clock = [datetime(2026, 11, 20, 12, tzinfo=UTC)]
    fsm = await storage(tmp_path, now=lambda: clock[0])
    await fsm.set_state(OTHER, "Flow:step")  # also the first purge (nothing old yet)
    fsm._purged_at = float("-inf")  # pretend an hour has passed since that purge
    clock[0] += timedelta(days=2)
    await fsm.set_state(KEY, "Flow:step")  # any write purges what has expired
    assert await fsm.count() == 1


async def test_unreadable_data_starts_afresh(tmp_path: Path) -> None:
    fsm = await storage(tmp_path)
    await fsm.set_data(KEY, {"a": 1})
    async with fsm._session_factory() as session:
        await session.execute(update(FsmStateORM).values(data="{broken"))
        await session.commit()
    assert await fsm.get_data(KEY) == {}
    async with fsm._session_factory() as session:
        await session.execute(update(FsmStateORM).values(data="[1, 2]"))
        await session.commit()
    assert await fsm.get_data(KEY) == {}


async def test_the_questionnaire_goes_on_after_a_restart(
    tmp_path: Path, settings: Settings
) -> None:
    database = tmp_path / "bot.db"
    async with bot_app(database, settings) as before:
        await before.say("/start")
        await before.press("consent:ok")
        await before.press("sex:female")
        await before.say("32")
    async with bot_app(database, settings) as after:  # a new bot process, same database
        replies = await after.say("168")
        assert texts.ASK_WEIGHT in [r.text for r in replies]
        await after.say("64,5")
        await after.press("act:light")
        await after.press("goal:lose")
        async with after.session_factory() as session:
            profile = await UserRepository(session).get_profile(1)
        assert profile is not None
        assert (profile.age, profile.height_cm) == (32, 168.0)
