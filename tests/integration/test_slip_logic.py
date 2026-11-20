"""Slip arithmetic end to end: several slips add up, "instead of a meal", today's menu day."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.models import MealType
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.core.nutrition import meal_nutrients
from nutrition_bot.db.models import MenuORM
from nutrition_bot.db.repositories.users import UserRepository
from tests.integration.bot_harness import BotHarness
from tests.integration.test_handlers_flow import PROFILE


async def deltas(app: BotHarness) -> list[float]:
    async with app.session_factory() as session:
        return await UserRepository(session).get_adjustments(1)


async def slip(app: BotHarness, text: str, choice: str = "slipc:yes") -> str:
    await app.say("/slip")
    await app.say(text)
    return (await app.press(choice))[-1].text


async def test_a_second_slip_adds_to_the_first(app: BotHarness, settings: Settings) -> None:
    await app.onboard()
    await slip(app, "пончик")  # about 250 kcal: under the 3-day cap
    first = sum(await deltas(app))
    await slip(app, "бутылка пива")  # about 215 kcal more
    second = sum(await deltas(app))
    assert second < first < 0  # more is cut, the first slip is not forgotten
    await slip(app, "2 куска пиццы")  # more than is left: the days stay at the cap
    cap = (
        settings.slip.max_daily_correction
        * calculate_daily_norm(PROFILE, settings.norms).target.kcal
    )
    assert all(d >= -cap - 1e-6 for d in await deltas(app))


async def test_quick_sizes_add_up_too(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    await app.press("slipq:small")
    first = sum(await deltas(app))
    await app.say("/slip")
    await app.press("slipq:small")
    assert sum(await deltas(app)) < first


async def test_a_small_food_instead_of_lunch_is_under_the_plan(app: BotHarness) -> None:
    await app.onboard()
    answer = await slip(app, "банан", "slipc:instead:lunch")
    assert texts.SLIP_TEXTS[next(o for o in texts.SLIP_TEXTS if o.value == "under_plan")] in answer
    assert answer.startswith("Учла, что это было вместо обеда")
    assert await deltas(app) == []


async def test_instead_cuts_less_than_on_top(make_app) -> None:  # type: ignore[no-untyped-def]
    on_top, instead = await make_app(), await make_app()
    for app in (on_top, instead):
        await app.onboard()
    await slip(on_top, "2 куска пиццы, бутылка пива")
    await slip(instead, "2 куска пиццы, бутылка пива", "slipc:instead:dinner")
    assert sum(await deltas(on_top)) < sum(await deltas(instead)) <= 0


async def test_the_plan_of_today_is_the_menu_day_by_date(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:3")
    await app.press("pantry:any")
    async with app.session_factory() as session:
        await session.execute(
            update(MenuORM).values(created_at=datetime.now(UTC) - timedelta(days=1))
        )
        await session.commit()
        menu = await UserRepository(session).get_menu(1)
    assert menu
    lunch = next(m for m in menu[1] if m.meal_type is MealType.LUNCH)  # day 2 is today
    expected = round(meal_nutrients(app.catalog, lunch).kcal)
    answer = await slip(app, "банан", "slipc:instead:lunch")
    assert f"по плану около {expected} ккал" in answer


async def test_an_unknown_choice_does_nothing(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    await app.say("банан")
    assert await app.press("slipc:instead:brunch") == []
    assert await app.press("slipc:maybe") == []
    assert await deltas(app) == []
