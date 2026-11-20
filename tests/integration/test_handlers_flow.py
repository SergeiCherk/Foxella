"""End-to-end conversations through the real dispatcher, handlers and database."""

import logging
import re

import pytest
from sqlalchemy.exc import SQLAlchemyError

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.metrics import EventName
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.db.models import UserORM
from nutrition_bot.db.repositories.events import EventRepository
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.logging_setup import setup_logging
from tests.integration.bot_harness import BotHarness, Reply

PROFILE = Profile(Sex.FEMALE, 32, 168.0, 64.5, ActivityLevel.LIGHT, Goal.LOSE)
FORBIDDEN = ("срыв", "штраф", "грех", "провинил", "виноват")


def joined(replies: list[Reply]) -> str:
    return "\n".join(r.text for r in replies)


async def stored_profile(app: BotHarness, user_id: int = 1) -> Profile | None:
    async with app.session_factory() as session:
        return await UserRepository(session).get_profile(user_id)


async def make_menu(app: BotHarness, days: int = 1, pantry: str | None = None) -> list[Reply]:
    await app.say("/menu")
    await app.press(f"days:{days}")
    if pantry is None:
        return await app.press("pantry:any")
    return await app.say(pantry)


# ------------------------------------------------------------------ onboarding


async def test_start_shows_disclaimer_and_waits_for_the_button(app: BotHarness) -> None:
    replies = await app.say("/start")
    assert len(replies) == 1
    assert texts.DISCLAIMER in replies[0].text
    assert replies[0].buttons == ("consent:ok",)
    asked = await app.press("consent:ok")
    assert asked[-1].text == texts.ASK_SEX
    assert set(asked[-1].buttons) == {"sex:male", "sex:female"}


async def test_questions_are_not_asked_before_the_button(app: BotHarness) -> None:
    await app.say("/start")
    replies = await app.say("32")
    assert replies[-1].text == texts.CONSENT_REMINDER
    assert replies[-1].buttons == ("consent:ok",)
    assert await app.press("sex:female") == []  # the sex step is not open yet


async def test_a_command_while_waiting_for_the_button_is_still_a_command(app: BotHarness) -> None:
    await app.say("/start")
    assert (await app.say("/menu"))[-1].text == texts.NEED_PROFILE


async def test_the_confirmation_time_is_stored_with_the_profile(app: BotHarness) -> None:
    await app.onboard()
    async with app.session_factory() as session:
        repo = UserRepository(session)
        assert await repo.has_accepted_disclaimer(1)
        user = await session.get(UserORM, 1)
        assert user is not None
        assert user.disclaimer_accepted_at is not None


async def test_editing_the_profile_keeps_the_first_confirmation(app: BotHarness) -> None:
    await app.onboard()
    async with app.session_factory() as session:
        first = (await session.get(UserORM, 1)).disclaimer_accepted_at  # type: ignore[union-attr]
    await app.press("profile:edit")
    await app.press("sex:female")
    await app.say("33")
    await app.say("168")
    await app.say("64")
    await app.press("act:light")
    await app.press("goal:maintain")
    async with app.session_factory() as session:
        user = await session.get(UserORM, 1)
        assert user is not None
        assert user.disclaimer_accepted_at == first


async def test_a_person_from_before_the_button_confirms_on_the_next_start(
    app: BotHarness,
) -> None:
    await app.onboard()
    async with app.session_factory() as session:
        user = await session.get(UserORM, 1)
        assert user is not None
        user.disclaimer_accepted_at = None  # how people saved before this version look
        await session.commit()
    replies = await app.say("/start")
    assert replies[-1].buttons == ("consent:ok",)
    assert await stored_profile(app) == PROFILE  # nothing is asked again, nothing is lost
    done = await app.press("consent:ok")
    assert done[-1].text == texts.WELCOME_BACK
    async with app.session_factory() as session:
        assert await UserRepository(session).has_accepted_disclaimer(1)
    assert (await app.say("/start"))[-1].text == texts.WELCOME_BACK  # not asked a second time


async def test_the_button_pressed_after_a_restart_still_starts_the_questions(
    app: BotHarness,
) -> None:
    # The conversation state lives in memory, so a restart forgets it; the button must still work.
    replies = await app.press("consent:ok")
    assert replies[-1].text == texts.ASK_SEX


async def test_full_onboarding_saves_profile_and_shows_norm_from_code(
    app: BotHarness, settings: Settings
) -> None:
    replies = await app.onboard()
    assert await stored_profile(app) == PROFILE
    target = calculate_daily_norm(PROFILE, settings.norms).target
    assert f"{round(target.kcal)} ккал" in replies[-1].text
    assert replies[-1].buttons == ("menu:start", "goalcheck:start", "diet:show")  # lose


@pytest.mark.parametrize("age", ["17", "5", "17 лет"])
async def test_minors_are_refused_and_nothing_is_stored(app: BotHarness, age: str) -> None:
    await app.say("/start")
    await app.press("consent:ok")
    await app.press("sex:male")
    replies = await app.say(age)
    assert replies[-1].text == texts.UNDERAGE
    assert await stored_profile(app) is None
    again = await app.say("30")  # the conversation is over: no longer taken as an age answer
    assert again[-1].text == texts.FALLBACK


@pytest.mark.parametrize(
    ("step", "answer", "expected"),
    [
        ("age", "abc", "Не получилось"),
        ("age", "250", "от 18 до 100"),
        ("height", "50", "от 120 до 230"),
        ("height", "1,7 м", "Не получилось"),
        ("weight", "5", "от 30 до 300"),
        ("weight", "", "Не получилось"),
    ],
)
async def test_bad_numbers_are_asked_again(
    app: BotHarness, step: str, answer: str, expected: str
) -> None:
    await app.say("/start")
    await app.press("consent:ok")
    await app.press("sex:female")
    if step in ("height", "weight"):
        await app.say("32")
    if step == "weight":
        await app.say("168")
    replies = await app.say(answer or "   ")
    assert expected in replies[-1].text


async def test_numbers_accept_units_and_decimal_comma(app: BotHarness) -> None:
    await app.say("/start")
    await app.press("consent:ok")
    await app.press("sex:male")
    await app.say("40 лет")
    await app.say("181 см")
    await app.say("82,5 кг")
    await app.press("act:high")
    await app.press("goal:gain")
    saved = await stored_profile(app)
    assert saved == Profile(Sex.MALE, 40, 181.0, 82.5, ActivityLevel.HIGH, Goal.GAIN)


async def test_command_in_the_middle_leaves_the_conversation(app: BotHarness) -> None:
    await app.say("/start")
    await app.press("consent:ok")
    await app.press("sex:female")
    replies = await app.say("/menu")
    assert replies[-1].text == texts.NEED_PROFILE
    assert (await app.say("32"))[-1].text == texts.FALLBACK


async def test_start_for_a_known_person_does_not_ask_again(app: BotHarness) -> None:
    await app.onboard()
    replies = await app.say("/start")
    assert replies[-1].text == texts.WELCOME_BACK


async def test_stale_buttons_are_ignored(app: BotHarness) -> None:
    assert await app.press("sex:female") == []  # no conversation is waiting for it
    await app.say("/start")
    assert await app.press("sex:alien") == []  # unknown value: nothing happens
    assert (await app.say("32"))[-1].text != texts.ASK_HEIGHT


# ----------------------------------------------------------------------- menu


async def test_menu_needs_a_profile(app: BotHarness) -> None:
    assert (await app.say("/menu"))[-1].text == texts.NEED_PROFILE


async def test_menu_for_any_products_shows_household_measures_only(app: BotHarness) -> None:
    await app.onboard()
    replies = await make_menu(app, days=1)
    text = joined(replies)
    assert "День 1" in text
    for meal in ("Завтрак", "Обед", "Перекус", "Ужин"):
        assert meal in text
    items = [line for line in text.splitlines() if line.startswith("• ")]
    assert items
    assert not [line for line in items if re.search(r"\d\s*(г|гр|грамм|кг|мл)\b", line)]
    assert replies[-1].buttons == ("shop:show", "slip:start")
    async with app.session_factory() as session:
        menu = await UserRepository(session).get_menu(1)
    assert menu is not None
    assert len(menu) == 1


async def test_menu_calories_are_computed_by_code_and_close_to_the_norm(
    app: BotHarness, settings: Settings
) -> None:
    await app.onboard()
    text = joined(await make_menu(app))
    target = calculate_daily_norm(PROFILE, settings.norms).target.kcal
    shown = int(re.search(r"День 1</b>\n🔥 <b>(\d+) ккал", text).group(1))  # type: ignore[union-attr]
    assert abs(shown - target) / target < 0.12


async def test_menu_for_three_days_uses_the_users_products(app: BotHarness) -> None:
    await app.onboard()
    replies = await make_menu(app, days=3, pantry="гречка, куриная грудка, огурцы, яйца, брокколи")
    text = joined(replies)
    assert all(f"День {n}" in text for n in (1, 2, 3))
    async with app.session_factory() as session:
        repo = UserRepository(session)
        pantry = await repo.get_pantry(1)
        menu = await repo.get_menu(1)
    assert len(pantry) == 5
    assert menu is not None
    assert len(menu) == 3


async def test_ambiguous_product_is_clarified_with_buttons(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:1")
    replies = await app.say("творог, гречка")
    assert "творог" in replies[-1].text
    assert any(b.startswith("pick:") for b in replies[-1].buttons)
    assert {"pick:all", "pick:skip"} <= set(replies[-1].buttons)
    choice = next(b for b in replies[-1].buttons if b not in ("pick:all", "pick:skip"))
    final = await app.press(choice)
    assert "День 1" in joined(final)
    async with app.session_factory() as session:
        assert len(await UserRepository(session).get_pantry(1)) == 2


async def test_clarify_any_adds_every_option_and_skip_adds_none(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app, pantry="сыр")  # asks which cheese
    final = await app.press("pick:all")
    assert "День 1" in joined(final)
    async with app.session_factory() as session:
        assert len(await UserRepository(session).get_pantry(1)) >= 3
    await app.say("/menu")
    await app.press("days:1")
    await app.say("сыр")
    final = await app.press("pick:skip")
    assert "День 1" in joined(final)  # nothing chosen = any products
    async with app.session_factory() as session:
        assert await UserRepository(session).get_pantry(1) == []


async def test_unknown_products_are_named_and_skipped(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:1")
    replies = await app.say("гречка, бетон")
    assert "бетон" in replies[0].text
    assert "День 1" in joined(replies)


async def test_only_unknown_products_ask_again_and_stay_in_the_step(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:1")
    replies = await app.say("абракадабра")
    assert replies[-1].text == texts.MENU_PRODUCTS_AGAIN
    assert "День 1" in joined(await app.press("pantry:any"))


async def test_same_products_as_last_time(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app, pantry="гречка, куриная грудка")
    await app.say("/menu")
    replies = await app.press("days:2")
    assert "pantry:last" in replies[-1].buttons
    assert "День 2" in joined(await app.press("pantry:last"))
    async with app.session_factory() as session:
        assert len(await UserRepository(session).get_pantry(1)) == 2


async def test_invalid_days_button_is_ignored(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    assert await app.press("days:9") == []
    assert await app.press("days:x") == []


async def test_menu_shows_balance_hints_when_the_pantry_lacks_vegetables(app: BotHarness) -> None:
    await app.onboard()
    text = joined(await make_menu(app, pantry="рис, куриная грудка"))
    assert texts.HINTS_TITLE in text


# ------------------------------------------------------------------- shopping


async def test_shopping_without_a_menu(app: BotHarness) -> None:
    await app.onboard()
    assert (await app.say("/shopping"))[-1].text == texts.NO_MENU


async def test_shopping_list_has_raw_foods_in_measures_and_skips_owned(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app, days=2, pantry="куриная грудка, гречка")
    for replies in (await app.say("/shopping"), await app.press("shop:show")):
        text = joined(replies)
        assert "Список покупок" in text
        assert "Куриная грудка (сырая)" not in text  # the user already has it
        assert "Гречка (сухая)" not in text
        assert "(варёная)" not in text  # cooked foods are converted to what you buy
        assert not re.search(r"—\s*[\d,]+\s*(г|кг)\b", text)


async def test_shopping_when_everything_is_at_home_says_so(
    app: BotHarness,
) -> None:
    await app.onboard()
    await make_menu(app)  # any products: nothing is "owned", so the list is not empty
    assert "Список покупок" in joined(await app.say("/shopping"))
    async with app.session_factory() as session:
        menu = await UserRepository(session).get_menu(1)
        assert menu is not None
        owned = {i.food_id for d in menu for m in d for dish in m.dishes for i in dish.items}
        await UserRepository(session).set_pantry(1, owned)
    assert (await app.say("/shopping"))[-1].text == texts.SHOPPING_ALL_OWNED


async def test_shopping_with_a_damaged_menu_asks_for_a_new_one(app: BotHarness) -> None:
    from sqlalchemy import update

    from nutrition_bot.db.models import MenuORM

    await app.onboard()
    await make_menu(app)
    async with app.session_factory() as session:
        await session.execute(update(MenuORM).values(payload="not json"))
        await session.commit()
    assert (await app.say("/shopping"))[-1].text == texts.NO_MENU


# ----------------------------------------------------------------------- slip


async def test_slip_needs_a_profile(app: BotHarness) -> None:
    assert (await app.say("/slip"))[-1].text == texts.NEED_PROFILE


async def test_slip_with_rough_size_spreads_a_small_correction(
    app: BotHarness, settings: Settings
) -> None:
    await app.onboard()
    replies = await app.say("/slip")
    assert replies[-1].text == texts.SLIP_ASK
    assert {"slipq:small", "slipq:medium", "slipq:large"} <= set(replies[-1].buttons)
    answer = joined(await app.press("slipq:large"))
    assert not [w for w in FORBIDDEN if w in answer.lower()]
    norm = calculate_daily_norm(PROFILE, settings.norms)
    async with app.session_factory() as session:
        deltas = await UserRepository(session).get_adjustments(1)
    assert len(deltas) == settings.slip.spread_days
    cap = settings.slip.max_daily_correction * norm.target.kcal
    assert all(-cap - 1e-6 <= d <= 0 for d in deltas)
    assert norm.target.kcal + min(deltas) >= norm.floor_kcal


async def test_tiny_excess_changes_nothing(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    await app.say("огурец")  # about 25 kcal: inside the tolerance
    answer = (await app.press("slipc:yes"))[-1].text
    assert "Продолжаем по плану" in answer
    assert texts.SLIP_NEXT_MENU not in answer
    async with app.session_factory() as session:
        assert await UserRepository(session).get_adjustments(1) == []


async def day_kcal(replies: list[Reply]) -> int:
    match = re.search(r"День 1</b>\n🔥 <b>(\d+) ккал", joined(replies))
    assert match is not None
    return int(match.group(1))


async def test_the_next_menu_uses_the_correction_once(app: BotHarness) -> None:
    await app.onboard(user_id=1)
    await app.onboard(user_id=2)  # the same person, who did not slip: the reference
    await app.say("/slip")
    await app.press("slipq:large")
    async with app.session_factory() as session:
        first = (await UserRepository(session).get_adjustments(1))[0]
    assert first < -50
    with_correction = await day_kcal(await make_menu(app))
    await app.say("/menu", 2)
    await app.press("days:1", 2)
    reference = await day_kcal(await app.press("pantry:any", 2))
    assert with_correction <= reference + first / 2  # clearly lower, by about the correction
    async with app.session_factory() as session:
        assert await UserRepository(session).get_adjustments(1) == []  # used up
    again = await day_kcal(await make_menu(app))
    assert again == pytest.approx(reference, abs=40)  # the next menu is back to normal


async def test_slip_with_a_list_of_foods_is_confirmed_before_counting(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("2 банана, 3 яйца")
    assert "ккал сверх плана" in replies[-1].text
    assert replies[-1].buttons == ("slipc:yes", "slipc:redo")
    assert "Банан" in replies[-1].text
    done = await app.press("slipc:yes")
    assert done
    async with app.session_factory() as session:
        assert await UserRepository(session).get_adjustments(1) is not None


async def test_slip_understands_ready_dishes_and_their_measures(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("тарелка борща, 2 куска пиццы и банка колы")
    text = replies[-1].text
    assert "Борщ — <b>1 тарелка</b>" in text
    assert "Пицца с сыром — <b>2 куска</b>" in text
    assert "Кола — <b>1 банка</b>" in text
    # 300 g borscht + 220 g pizza + 330 g cola, computed from the catalog
    assert "ккал сверх плана" in text


async def test_slip_redo_asks_again(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    await app.say("банан")
    replies = await app.press("slipc:redo")
    assert replies[-1].text == texts.SLIP_ASK


async def test_slip_unknown_food_offers_rough_sizes(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("бетон")
    assert texts.SLIP_NOTHING in replies[-1].text
    assert "slipq:large" in replies[-1].buttons


async def test_slip_ambiguous_food_is_clarified(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("творог")
    assert any(b.startswith("spick:") for b in replies[-1].buttons)
    choice = next(b for b in replies[-1].buttons if b not in ("spick:all", "spick:skip"))
    assert "ккал сверх плана" in (await app.press(choice))[-1].text
    await app.say("/slip")
    await app.say("творог")
    assert (await app.press("spick:skip"))[-1].text.startswith(texts.SLIP_NOTHING[:20])


async def test_slip_button_under_a_menu_starts_the_flow(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app)
    assert (await app.press("slip:start"))[-1].text == texts.SLIP_ASK


async def test_slip_against_a_saved_menu_uses_that_days_plan(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app, days=2)
    await app.say("/slip")
    assert (await app.press("slipq:large"))[-1].text


# -------------------------------------------------------------------- profile


async def test_profile_view_and_edit(app: BotHarness, settings: Settings) -> None:
    await app.onboard()
    replies = await app.say("/profile")
    assert "168" in replies[-1].text
    assert "64,5" in replies[-1].text
    assert str(round(calculate_daily_norm(PROFILE, settings.norms).target.kcal)) in replies[-1].text
    assert set(replies[-1].buttons) == {"profile:edit", "goalcheck:start", "diet:show", "del:ask"}
    assert (await app.press("profile:edit"))[-1].text == texts.ASK_SEX


async def test_profile_without_data(app: BotHarness) -> None:
    assert (await app.say("/profile"))[-1].text == texts.NEED_PROFILE


async def test_delete_me_erases_everything(app: BotHarness) -> None:
    await app.onboard()
    await make_menu(app, pantry="гречка")
    ask = await app.say("/delete_me")
    assert ask[-1].buttons == ("del:yes", "del:no")
    assert (await app.press("del:yes"))[-1].text == texts.DELETE_DONE
    assert await stored_profile(app) is None
    async with app.session_factory() as session:
        repo = UserRepository(session)
        assert await repo.get_menu(1) is None
        assert await repo.get_pantry(1) == []
    assert (await app.press("del:yes"))[-1].text == texts.DELETE_NOTHING


async def test_delete_can_be_cancelled(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/delete_me")
    assert (await app.press("del:no"))[-1].text == texts.CANCELLED
    assert await stored_profile(app) == PROFILE


async def test_delete_from_the_profile_button(app: BotHarness) -> None:
    await app.onboard()
    assert (await app.press("del:ask"))[-1].buttons == ("del:yes", "del:no")


async def test_people_do_not_see_each_others_data(app: BotHarness) -> None:
    await app.onboard(user_id=1)
    assert (await app.say("/menu", user_id=2))[-1].text == texts.NEED_PROFILE
    await app.say("/delete_me", user_id=2)
    await app.press("del:yes", user_id=2)
    assert await stored_profile(app, 1) == PROFILE


# ------------------------------------------------------------ fallback, errors


async def test_unknown_text_gets_the_command_list(app: BotHarness) -> None:
    assert (await app.say("привет"))[-1].text == texts.FALLBACK


async def test_a_crash_is_reported_politely_and_does_not_leak_text(
    app: BotHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(*_args: object) -> None:
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(UserRepository, "get_profile", boom)
    with caplog.at_level(logging.ERROR):
        replies = await app.say("/profile")
    assert replies[-1].text == texts.ERROR_GENERIC
    assert "handler failed: RuntimeError" in caplog.text


async def test_user_text_never_reaches_the_logs(
    app: BotHarness, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "суперсекретныйпродукт"
    setup_logging("DEBUG")  # the worst case: someone switched on debug logging
    with caplog.at_level(logging.DEBUG):
        await app.onboard()
        await make_menu(app, pantry=f"гречка, {secret}")
        await app.say("/slip")
        await app.say(secret)
        await app.say(f"/{secret}")
    assert secret not in caplog.text
    assert "168" not in caplog.text


# ------------------------------------------------------------ beta usage events


async def stored_events(app: BotHarness, user_id: int = 1) -> list[EventName]:
    async with app.session_factory() as session:
        return [e.name for e in await EventRepository(session).all_events() if e.user_id == user_id]


async def test_events_follow_the_journey_of_one_person(app: BotHarness) -> None:
    assert await stored_events(app) == []
    await app.onboard()
    assert await stored_events(app) == [EventName.ONBOARDING_DONE]
    await make_menu(app)
    assert await stored_events(app) == [EventName.ONBOARDING_DONE, EventName.MENU_RECEIVED]
    await app.say("/slip")
    await app.press("slip:start")  # the button under a menu counts too
    assert await stored_events(app) == [
        EventName.ONBOARDING_DONE,
        EventName.MENU_RECEIVED,
        EventName.SLIP_PRESSED,
        EventName.SLIP_PRESSED,
    ]


async def test_editing_the_profile_is_not_a_new_onboarding(app: BotHarness) -> None:
    await app.onboard()
    await app.press("profile:edit")
    await app.press("sex:male")
    await app.say("40")
    await app.say("180")
    await app.say("80")
    await app.press("act:light")
    await app.press("goal:maintain")
    assert (await stored_profile(app)) is not None
    assert await stored_events(app) == [EventName.ONBOARDING_DONE]


async def test_nothing_is_recorded_without_a_profile_or_without_a_menu(app: BotHarness) -> None:
    await app.say("/slip")
    await app.say("/menu")
    await app.say("/shopping")
    assert await stored_events(app) == []
    await app.say("/start")  # onboarding started but not finished
    await app.press("consent:ok")
    await app.press("sex:female")
    assert await stored_events(app) == []


async def test_a_refused_minor_leaves_no_event(app: BotHarness) -> None:
    await app.say("/start")
    await app.press("consent:ok")
    await app.press("sex:female")
    assert (await app.say("15"))[-1].text == texts.UNDERAGE
    assert await stored_events(app) == []


async def test_events_of_different_people_are_kept_apart(app: BotHarness) -> None:
    await app.onboard(user_id=1)
    await app.onboard(user_id=2)
    await app.say("/slip", user_id=2)
    assert await stored_events(app, 1) == [EventName.ONBOARDING_DONE]
    assert await stored_events(app, 2) == [EventName.ONBOARDING_DONE, EventName.SLIP_PRESSED]


async def test_delete_me_erases_the_events_too(app: BotHarness) -> None:
    await app.onboard(user_id=1)
    await app.onboard(user_id=2)
    await make_menu(app)
    await app.say("/delete_me")
    await app.press("del:yes")
    assert await stored_events(app, 1) == []
    assert await stored_events(app, 2) == [EventName.ONBOARDING_DONE]


async def test_a_failing_statistics_write_does_not_break_the_bot(
    app: BotHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(self: EventRepository, telegram_id: int, name: EventName) -> None:
        raise SQLAlchemyError("disk is full")

    monkeypatch.setattr(EventRepository, "record", broken)
    with caplog.at_level(logging.WARNING):
        replies = await app.onboard()
        menu = await make_menu(app)
        slip = await app.say("/slip")
    assert replies[-1].buttons[0] == "menu:start"
    assert "ккал" in joined(menu)
    assert slip[-1].text == texts.SLIP_ASK
    assert await stored_profile(app) == PROFILE
    assert "could not record the onboarding_done event" in caplog.text


# ---- whatever a person types is escaped: the harness fails on any invalid Telegram HTML


async def test_typed_html_in_products_is_shown_escaped(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:1")
    replies = await app.say("гречка, <b>бетон</b> & щебень")
    assert "&lt;b&gt;бетон&lt;/b&gt; &amp; щебень" in replies[0].text
    assert "День 1" in joined(replies)


async def test_typed_html_in_a_clarifying_question_is_escaped(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("творог <3")
    assert "«<b>творог &lt;3</b>»" in replies[-1].text
    assert "spick:skip" in replies[-1].buttons


async def test_typed_html_in_slip_is_escaped(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("банан, <script>")
    assert "&lt;script&gt;" in replies[0].text


async def test_profile_shows_age_with_the_right_word(app: BotHarness) -> None:
    await app.onboard()  # 32 years
    text = (await app.say("/profile"))[-1].text
    assert "Возраст: <b>32 года</b>" in text
    assert "Цель: <b>похудеть</b>" in text
