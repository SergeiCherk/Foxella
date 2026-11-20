"""Food the bot does not know in "I ate": the model splits it into our foods, the person checks."""

import json

from nutrition_bot import texts
from nutrition_bot.core.errors import LLMError
from nutrition_bot.services.llm import FakeLLM
from tests.integration.bot_harness import BotHarness
from tests.integration.conftest import AppFactory


def lagman(app: BotHarness, phrase: str = "тарелка лагмана") -> str:
    def item(code: str, quantity: float) -> dict[str, object]:
        food = next(f for f in app.catalog.foods if f.code == code)
        measure = app.catalog.measures_for(food.id)[0]
        return {"food_id": food.id, "measure_id": measure.id, "quantity": quantity}

    items = [item("pasta_cooked", 2), item("beef_lean_cooked", 1), item("sunflower_oil", 1)]
    return json.dumps({"foods": [{"phrase": phrase, "items": items}]}, ensure_ascii=False)


async def test_unknown_food_is_split_by_the_model_and_shown_for_checking(
    make_app: AppFactory,
) -> None:
    probe = await make_app()
    llm = FakeLLM(eaten=[lagman(probe)])
    app = await make_app(llm=llm)
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("тарелка лагмана, банан")
    said = [r.text for r in replies]
    assert said[0] == texts.SLIP_GUESSING.format(items="тарелка лагмана")
    assert texts.SLIP_GUESSED.format(items="тарелка лагмана") in said
    confirm = replies[-1].text
    assert "Макароны (варёные)" in confirm
    assert "Банан" in confirm  # the known food stays as it was
    assert "<b>сверх плана</b> или <b>вместо</b>" in confirm
    assert llm.eaten_requests[0].phrases == ("тарелка лагмана",)
    # the model sees only plain foods: no ready dishes, nothing raw
    borscht = next(f.id for f in app.catalog.foods if f.code == "borscht")
    assert borscht not in llm.eaten_requests[0].allowed_food_ids
    await app.press("slipc:yes")


async def test_without_a_model_unknown_food_is_reported_as_before(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("лагман, банан")
    assert replies[0].text == texts.SLIP_UNKNOWN.format(items="лагман")
    assert all(texts.SLIP_GUESSING.split("<i>")[0] not in r.text for r in replies)


async def test_a_failing_model_leaves_the_food_unknown(make_app: AppFactory) -> None:
    app = await make_app(llm=FakeLLM(eaten=[LLMError("down")]))
    await app.onboard()
    await app.say("/slip")
    replies = await app.say("лагман")
    assert texts.SLIP_UNKNOWN.format(items="лагман") in [r.text for r in replies]
    assert texts.SLIP_NOTHING in replies[-1].text


async def test_the_model_is_asked_at_most_once_in_a_short_while(make_app: AppFactory) -> None:
    probe = await make_app()
    llm = FakeLLM(eaten=[lagman(probe, "лагман"), lagman(probe, "лагман")])
    app = await make_app(llm=llm)
    await app.onboard()
    await app.say("/slip")
    await app.say("лагман")
    await app.press("slipc:redo")
    replies = await app.say("лагман")
    assert len(llm.eaten_requests) == 1  # the pause (SlipConfig.llm_cooldown_s) holds it back
    assert texts.SLIP_UNKNOWN.format(items="лагман") in [r.text for r in replies]
