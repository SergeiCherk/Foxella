"""The scenario that motivated the staples fix: a short list of products, a believable menu."""

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.menu import menu_food_ids, staple_food_ids
from nutrition_bot.db.repositories.users import UserRepository
from tests.integration.bot_harness import BotHarness, Reply
from tests.integration.test_handlers_flow import joined

LIST = "курица, гречка, помидоры, огурцы, яйца, творог"


async def typed_menu(app: BotHarness, text: str, days: int = 1) -> list[Reply]:
    await app.say("/menu")
    await app.press(f"days:{days}")
    replies = await app.say(text)
    while replies and replies[-1].buttons and replies[-1].buttons[0].startswith("pick:"):
        replies = await app.press(replies[-1].buttons[0])  # "which chicken?": take the first
    return replies


async def stored_menu_food_ids(app: BotHarness) -> set[int]:
    async with app.session_factory() as session:
        menu = await UserRepository(session).get_menu(1)
    assert menu
    return {
        item.food_id for day in menu for meal in day for dish in meal.dishes for item in dish.items
    }


async def test_a_short_list_gives_a_day_made_only_of_the_users_foods(
    app: BotHarness, settings: Settings
) -> None:
    await app.onboard()
    text = joined(await typed_menu(app, LIST))
    assert "День 1" in text
    assert texts.MENU_EXTRA_NOTE not in text  # nothing foreign had to be added

    async with app.session_factory() as session:
        pantry = await UserRepository(session).get_pantry(1)
    staples = staple_food_ids(app.catalog, settings.menu.staple_codes)
    allowed = set(menu_food_ids(app.catalog, pantry, staples))
    used = await stored_menu_food_ids(app)
    assert used <= allowed, [app.catalog.get_food(i).name_ru for i in used - allowed]


async def test_staples_used_by_the_menu_are_listed_as_things_to_check(
    app: BotHarness, settings: Settings
) -> None:
    await app.onboard()
    await typed_menu(app, LIST)
    used = await stored_menu_food_ids(app)
    staples = set(staple_food_ids(app.catalog, settings.menu.staple_codes))
    used_staples = used & staples
    assert used_staples  # the day cooks with oil, which the user never listed

    shopping = joined(await app.say("/shopping"))
    assert texts.SHOPPING_STAPLES_TITLE in shopping
    block = shopping.split(texts.SHOPPING_STAPLES_TITLE, 1)[1]
    for food_id in used_staples:
        assert app.catalog.get_food(food_id).name_ru in block
    before_block = shopping.split(texts.SHOPPING_STAPLES_TITLE, 1)[0]
    assert "Масло" not in before_block  # not listed twice


async def test_the_warning_still_appears_when_foreign_foods_are_really_needed(
    app: BotHarness,
) -> None:
    await app.onboard()
    text = joined(await typed_menu(app, "яблоки"))
    assert "День 1" in text
    assert texts.MENU_EXTRA_NOTE in text  # lunch and dinner cannot be made of apples


async def test_the_old_behaviour_is_not_silently_restored_for_pantry_any(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:1")
    text = joined(await app.press("pantry:any"))
    assert "День 1" in text
    assert texts.MENU_EXTRA_NOTE not in text  # "any product": nothing is foreign
