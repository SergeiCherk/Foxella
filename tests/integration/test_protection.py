"""End-to-end tests of the safety additions: term check, doctor note, anti-spam, deadline."""

import asyncio
import math
import time

import pytest
from aiogram.methods import AnswerCallbackQuery, SendChatAction

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.errors import LLMError
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.core.norms import calculate_daily_norm, max_safe_weekly_change_kg
from nutrition_bot.handlers.goal import _kg
from nutrition_bot.handlers.guard import MenuGuard
from nutrition_bot.services.llm import FakeLLM
from tests.integration.bot_harness import BotHarness, Reply
from tests.integration.conftest import AppFactory
from tests.integration.test_handlers_flow import PROFILE, joined, make_menu, stored_profile
from tests.unit.core.test_menu_deadline import HangingLLM


async def onboard_as(
    app: BotHarness, sex: str, age: str, height: str, weight: str, activity: str, goal: str
) -> list[Reply]:
    await app.say("/start")
    await app.press("consent:ok")
    await app.press(f"sex:{sex}")
    await app.say(age)
    await app.say(height)
    await app.say(weight)
    await app.press(f"act:{activity}")
    return await app.press(f"goal:{goal}")


def answers(app: BotHarness) -> list[str | None]:
    return [r.text for r in app.session.requests if isinstance(r, AnswerCallbackQuery)]


# ------------------------------------------------- note for a very small norm


async def test_a_woman_below_the_minimum_gets_the_doctor_note(app: BotHarness) -> None:
    replies = await onboard_as(app, "female", "80", "150", "45", "sedentary", "lose")
    note = texts.LOW_KCAL_NOTE.format(minimum=1200, who="женщин")
    assert note in replies[-1].text
    profile = await stored_profile(app)
    assert profile is not None
    assert replies[-1].text.startswith(texts.ONBOARDING_DONE.split("{")[0])  # still the normal text
    shown = await app.say("/profile")
    assert note in shown[-1].text


async def test_a_man_below_the_minimum_sees_the_male_limit(app: BotHarness) -> None:
    replies = await onboard_as(app, "male", "90", "150", "40", "sedentary", "maintain")
    assert texts.LOW_KCAL_NOTE.format(minimum=1500, who="мужчин") in replies[-1].text


async def test_a_typical_user_gets_no_note(app: BotHarness) -> None:
    marker = "ниже обычного минимума"  # the special note; the generic text mentions a doctor too
    replies = await app.onboard()
    assert marker not in replies[-1].text
    assert marker not in (await app.say("/profile"))[-1].text


async def test_the_note_never_changes_the_computed_numbers(
    app: BotHarness, settings: Settings
) -> None:
    replies = await onboard_as(app, "female", "80", "150", "45", "sedentary", "lose")
    tiny = Profile(Sex.FEMALE, 80, 150.0, 45.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    kcal = calculate_daily_norm(tiny, settings.norms).target.kcal
    assert f"{round(kcal)} ккал" in replies[-1].text
    assert kcal < 1200  # not raised to the minimum: the doctor is suggested instead


# ----------------------------------------------------------- target weight


async def test_a_realistic_target_is_confirmed(app: BotHarness) -> None:
    await app.onboard()
    ask = await app.press("goalcheck:start")
    assert ask[-1].text == texts.GOAL_ASK_TARGET.format(weight="64,5")
    weeks = await app.say("60")
    assert weeks[-1].text == texts.GOAL_ASK_WEEKS
    assert weeks[-1].buttons == ("weeks:4", "weeks:8", "weeks:12", "weeks:24")
    result = await app.press("weeks:24")
    assert result[-1].text == texts.GOAL_OK.format(pace=_kg(4.5 / 24))
    assert await stored_profile(app) == PROFILE  # nothing about the target is stored


async def test_a_too_fast_target_is_refused_with_a_safe_term(
    app: BotHarness, settings: Settings
) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    await app.say("55")  # 9.5 kg below 64.5
    result = await app.press("weeks:4")
    safe = max_safe_weekly_change_kg(PROFILE, settings.norms)
    expected = texts.GOAL_TOO_FAST.format(
        weeks_asked=4, pace_asked=_kg(9.5 / 4), safe=_kg(safe), weeks=math.ceil(9.5 / safe)
    )
    assert result[-1].text == expected
    assert "около 28 нед." in expected  # 9.5 kg at about 0.34 kg per week
    assert await stored_profile(app) == PROFILE


async def test_ten_kilos_in_one_week_is_refused(app: BotHarness) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    await app.say("54,5")
    result = await app.say("1")
    assert "слишком быстро" in result[-1].text
    assert "За 1 нед." in result[-1].text


async def test_typed_terms_are_understood(app: BotHarness) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    await app.say("60 кг")
    assert (await app.say("24 недели"))[-1].text.startswith(texts.GOAL_OK[:20])


async def test_a_target_that_contradicts_the_goal_is_asked_again(app: BotHarness) -> None:
    await app.onboard()  # goal: lose
    await app.press("goalcheck:start")
    await app.say("70")  # heavier than now
    result = await app.press("weeks:12")
    assert result[-1].text == texts.GOAL_BAD_TARGET
    again = await app.say("60")  # the conversation is back at the target question
    assert again[-1].text == texts.GOAL_ASK_WEEKS


async def test_an_impossible_target_weight_is_asked_again(app: BotHarness) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    await app.say("20")
    assert (await app.press("weeks:12"))[-1].text == texts.GOAL_BAD_TARGET


async def test_text_that_is_not_a_number_keeps_the_question_open(app: BotHarness) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    assert (await app.say("много"))[-1].text == texts.GOAL_NOT_A_NUMBER
    assert (await app.say("60"))[-1].text == texts.GOAL_ASK_WEEKS


@pytest.mark.parametrize("bad_weeks", ["0", "105", "много"])
async def test_a_bad_term_is_asked_again(app: BotHarness, bad_weeks: str) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    await app.say("60")
    result = await app.say(bad_weeks)
    assert result[-1].text == texts.GOAL_BAD_WEEKS.format(max_weeks=104)
    assert (await app.press("weeks:24"))[-1].text.startswith(texts.GOAL_OK[:20])


async def test_no_safe_plan_for_a_very_small_user_points_to_a_doctor(app: BotHarness) -> None:
    await onboard_as(app, "female", "80", "150", "45", "sedentary", "lose")
    await app.press("goalcheck:start")
    await app.say("44")
    assert (await app.press("weeks:52"))[-1].text == texts.GOAL_NO_SAFE


async def test_the_check_is_for_goals_that_change_weight(app: BotHarness) -> None:
    replies = await app.onboard(goal="maintain")
    assert "goalcheck:start" not in replies[-1].buttons
    assert (await app.press("goalcheck:start"))[-1].text == texts.GOAL_NOT_NEEDED  # old button


async def test_a_gain_goal_is_checked_too(app: BotHarness) -> None:
    replies = await app.onboard(goal="gain")
    assert "goalcheck:start" in replies[-1].buttons
    await app.press("goalcheck:start")
    await app.say("70")
    assert "слишком быстро" in (await app.press("weeks:4"))[-1].text


async def test_the_check_without_a_profile_asks_to_get_acquainted(app: BotHarness) -> None:
    assert (await app.press("goalcheck:start"))[-1].text == texts.NEED_PROFILE


async def test_a_command_in_the_middle_ends_the_check(app: BotHarness) -> None:
    await app.onboard()
    await app.press("goalcheck:start")
    await app.say("60")
    shown = await app.say("/profile")
    assert "168" in shown[-1].text
    assert (await app.say("24"))[-1].text == texts.FALLBACK  # no longer taken as a term


# --------------------------------------------------------------- anti-spam


class Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


async def test_a_second_menu_within_the_pause_is_refused_without_calling_the_llm(
    make_app: AppFactory,
) -> None:
    clock, llm = Clock(), FakeLLM()
    app = await make_app(llm=llm, guard=MenuGuard(30.0, clock))
    await app.onboard()
    assert "День 1" in joined(await make_menu(app))
    calls = len(llm.requests)
    assert calls > 0

    blocked = await make_menu(app)
    assert joined(blocked).endswith(texts.MENU_COOLDOWN.format(seconds=30))
    assert "День 1" not in joined(blocked)
    assert len(llm.requests) == calls  # no paid request was made

    clock.now += 31
    assert "День 1" in joined(await make_menu(app))


async def test_a_menu_requested_while_one_is_building_is_refused(make_app: AppFactory) -> None:
    llm = _GatedLLM()
    app = await make_app(llm=llm, guard=MenuGuard(30.0))
    await app.onboard()
    first = asyncio.create_task(make_menu(app))
    await asyncio.wait_for(llm.started.wait(), timeout=5)

    second = await make_menu(app)  # the user presses the button again
    assert texts.MENU_BUSY in joined(second)

    llm.gate.set()
    assert "День 1" in joined(await asyncio.wait_for(first, timeout=10))


async def test_the_guard_is_released_after_a_crash(make_app: AppFactory) -> None:
    llm = FakeLLM([RuntimeError("boom")])  # not an LLMError: the build really crashes
    app = await make_app(llm=llm)
    await app.onboard()
    crashed = await make_menu(app)
    assert texts.ERROR_GENERIC in joined(crashed)
    assert "День 1" in joined(await make_menu(app))  # not stuck as "busy"


async def test_users_are_limited_separately(make_app: AppFactory) -> None:
    app = await make_app(guard=MenuGuard(30.0, Clock()))
    await app.onboard(user_id=1)
    await app.onboard(user_id=2)
    await app.say("/menu", 1)
    await app.press("days:1", 1)
    assert "День 1" in joined(await app.press("pantry:any", 1))
    await app.say("/menu", 2)
    await app.press("days:1", 2)
    assert "День 1" in joined(await app.press("pantry:any", 2))  # user 2 is not paused


class _GatedLLM:
    """Waits until the test opens the gate, then fails (so the built-in dishes are used)."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def generate(self, request: object) -> str:
        self.started.set()
        await self.gate.wait()
        raise LLMError("closed")


# ----------------------------------------------- deadline, typing, old buttons


async def test_a_stalled_provider_cannot_keep_the_user_waiting(
    make_app: AppFactory, settings: Settings
) -> None:
    fast = settings.model_copy(
        update={"menu": settings.menu.model_copy(update={"build_timeout_s": 0.3})}
    )
    llm = HangingLLM()
    app = await make_app(llm=llm, use=fast)
    await app.onboard()
    started = time.perf_counter()
    text = joined(await make_menu(app, days=2))
    assert time.perf_counter() - started < 5
    assert "День 1 из 2" in text
    assert len(llm.requests) == 1


async def test_the_bot_shows_that_it_is_typing_while_it_builds(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app)
    actions = [r for r in app.session.requests if isinstance(r, SendChatAction)]
    assert actions
    assert actions[0].action == "typing"


async def test_old_buttons_get_an_answer_instead_of_a_spinner(app: BotHarness) -> None:
    await app.press("foo:bar")
    await app.press("days:2")  # no menu conversation is open
    await app.press("weeks:12")
    assert answers(app) == [texts.STALE_BUTTON] * 3


async def test_working_buttons_are_never_called_stale(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app)
    await app.say("/profile")
    await app.press("goalcheck:start")
    await app.say("60")
    await app.press("weeks:24")
    assert texts.STALE_BUTTON not in answers(app)
