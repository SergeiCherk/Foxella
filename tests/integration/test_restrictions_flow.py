"""Food restrictions end to end: toggles in the profile, then menus without those foods."""

import json

from aiogram.methods import EditMessageReplyMarkup

from nutrition_bot import texts
from nutrition_bot.db.repositories.users import UserRepository
from nutrition_bot.services.llm import FakeLLM
from tests.integration.bot_harness import BotHarness
from tests.integration.conftest import AppFactory


async def restrictions(app: BotHarness) -> list[str]:
    async with app.session_factory() as session:
        return await UserRepository(session).get_restrictions(1)


async def menu_food_ids(app: BotHarness) -> set[int]:
    async with app.session_factory() as session:
        menu = await UserRepository(session).get_menu(1)
    assert menu
    return {i.food_id for day in menu for meal in day for d in meal.dishes for i in d.items}


async def test_the_profile_offers_restrictions_and_shows_the_toggles(app: BotHarness) -> None:
    await app.onboard()
    assert "diet:show" in (await app.say("/profile"))[-1].buttons
    replies = await app.press("diet:show")
    assert replies[-1].text == texts.RESTRICTIONS_ASK
    assert replies[-1].buttons[-1] == "diet:done"
    assert "diet:t:nuts" in replies[-1].buttons
    assert all(label.startswith("▫️") for label in replies[-1].button_labels[:-1])


async def test_toggles_are_saved_and_shown_ticked(app: BotHarness) -> None:
    await app.onboard()
    await app.press("diet:show")
    await app.press("diet:t:nuts")
    await app.press("diet:t:meat")
    assert await restrictions(app) == ["meat", "nuts"]  # in the config's order
    edit = [m for m in app.session.requests if isinstance(m, EditMessageReplyMarkup)][-1]
    assert edit.reply_markup is not None
    labels = [b.text for row in edit.reply_markup.inline_keyboard for b in row]
    assert "✅ Без мяса" in labels
    assert "✅ Без орехов" in labels
    await app.press("diet:t:meat")  # off again
    assert await restrictions(app) == ["nuts"]
    done = await app.press("diet:done")
    assert done[-1].text == texts.RESTRICTIONS_SAVED.format(items="без орехов")


async def test_no_restrictions_is_confirmed_too(app: BotHarness) -> None:
    await app.onboard()
    assert (await app.press("diet:done"))[-1].text == texts.RESTRICTIONS_NONE


async def test_an_unknown_toggle_changes_nothing(app: BotHarness) -> None:
    await app.onboard()
    await app.press("diet:t:chocolate")
    assert await restrictions(app) == []


async def test_restrictions_need_a_profile(app: BotHarness) -> None:
    assert (await app.press("diet:show"))[-1].text == texts.NEED_PROFILE


async def test_the_profile_lists_the_restrictions(app: BotHarness) -> None:
    await app.onboard()
    await app.press("diet:t:dairy")
    await app.press("diet:t:gluten")
    text = (await app.say("/profile"))[-1].text
    assert "🚫 Ограничения: <b>без молочного, без глютена</b>" in text


async def test_the_onboarding_result_offers_restrictions(app: BotHarness) -> None:
    replies = await app.onboard()
    assert "diet:show" in replies[-1].buttons


async def test_a_menu_has_no_forbidden_food(app: BotHarness) -> None:
    await app.onboard()
    await app.press("diet:t:meat")
    await app.press("diet:t:dairy")
    await app.say("/menu")
    await app.press("days:3")
    await app.press("pantry:any")
    used = await menu_food_ids(app)
    categories = {app.catalog.get_food(i).category.value for i in used}
    assert used
    assert not categories & {"meat", "dairy"}
    butter = next(f.id for f in app.catalog.foods if f.code == "butter")
    assert butter not in used  # dairy, though filed under fats


async def test_forbidden_foods_from_the_users_list_are_named_and_left_out(app: BotHarness) -> None:
    await app.onboard()
    await app.press("diet:t:fish")
    await app.say("/menu")
    await app.press("days:1")
    replies = await app.say("треска, гречка, огурцы")
    note = next(r.text for r in replies if r.text.startswith("Убрала из списка"))
    assert "Треска (сырая)" in note
    used = await menu_food_ids(app)
    assert not {app.catalog.get_food(i).category.value for i in used} & {"fish"}


async def test_the_model_is_refused_a_forbidden_food_in_a_recipe(make_app: AppFactory) -> None:
    """A model answer that sneaks cheese into a dairy-free person's recipe is sent back."""
    probe = await make_app()
    pasta = next(f for f in probe.catalog.foods if f.code == "pasta_cooked")
    measure = probe.catalog.measures_for(pasta.id)[0]
    answer = json.dumps(
        {"dishes": [{"name": "Паста", "recipe": "Посыпьте пасту сыром.",
                     "items": [{"food_id": pasta.id, "measure_id": measure.id, "quantity": 2}]}]},
        ensure_ascii=False,
    )  # fmt: skip
    llm = FakeLLM([answer] * 20)
    app = await make_app(llm=llm)
    await app.onboard()
    await app.press("diet:t:dairy")
    await app.say("/menu")
    await app.press("days:1")
    await app.press("pantry:any")
    feedback = [p for r in llm.requests for p in r.feedback]
    assert any("which this person does not eat" in p for p in feedback)
    used = await menu_food_ids(app)
    assert not {app.catalog.get_food(i).category.value for i in used} & {"dairy"}
