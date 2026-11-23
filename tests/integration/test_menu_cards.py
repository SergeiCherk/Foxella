"""Saved plans, dish details and contextual complaints through Telegram callbacks."""

from datetime import UTC, datetime, timedelta

from aiogram.methods import EditMessageText, SendMessage
from sqlalchemy import update

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.core.models import Dish, Meal, MealType
from nutrition_bot.db.models import MenuORM
from nutrition_bot.db.repositories.users import UserRepository
from tests.integration.bot_harness import BotHarness, Reply
from tests.integration.conftest import AppFactory


async def save_plan(app: BotHarness, age_days: int = 0) -> None:
    recipe = "1. Подготовьте продукты.\n" * 40 + "2. Последний шаг — подайте на стол."
    days = [(Meal(MealType.DINNER, (Dish(f"Блюдо <{n}>", (), recipe),)),) for n in range(1, 4)]
    async with app.session_factory() as session:
        await UserRepository(session).save_menu(1, days)
        if age_days:
            await session.execute(
                update(MenuORM).values(created_at=datetime.now(UTC) - timedelta(days=age_days))
            )
            await session.commit()


def button(reply: Reply, label: str) -> str:
    return reply.buttons[reply.button_labels.index(label)]


async def test_open_saved_today_and_browse_without_sending_new_messages(app: BotHarness) -> None:
    await app.onboard()
    await save_plan(app, age_days=1)
    (today,) = await app.say(texts.BTN_NAV_MENU)
    assert "День 2 из 3" in today.text
    assert texts.MENU_ASK_DAYS not in today.text
    (dish,) = await app.press(today.buttons[0])
    assert "Блюдо &lt;2&gt;" in dish.text
    assert "<blockquote expandable>" in dish.text
    assert "Последний шаг" in dish.text
    (back,) = await app.press(button(dish, "← К меню дня"))
    assert back == today
    (last,) = await app.press(button(back, "Следующий день →"))
    assert "День 3 из 3" in last.text
    assert "Следующий день →" not in last.button_labels
    assert sum(isinstance(request, EditMessageText) for request in app.session.requests) == 3
    (question,) = await app.press(button(last, "🍽 Составить новое"))
    assert question.text == texts.MENU_ASK_DAYS


async def test_expired_plan_and_stale_dish_button(app: BotHarness) -> None:
    await app.onboard()
    await save_plan(app, age_days=4)
    (old,) = await app.say("/menu")
    assert "День 3 из 3" in old.text
    assert "план уже закончился" in old.text
    await save_plan(app)
    assert await app.press(old.buttons[0]) == []


async def test_dish_complaint_reaches_owner_with_context(
    make_app: AppFactory, settings: Settings
) -> None:
    app = await make_app(use=settings.model_copy(update={"admin_ids": frozenset({777})}))
    await app.onboard()
    await save_plan(app)
    (overview,) = await app.say("/menu")
    (dish,) = await app.press(overview.buttons[0])
    (prompt,) = await app.press(button(dish, "⚠️ Сообщить о проблеме"))
    assert prompt.text == texts.FEEDBACK_ASK_COMPLAINT
    replies = await app.say("Непонятен шаг & температура")
    assert replies[-1].text == texts.FEEDBACK_SENT
    (notice,) = [m for m in app.session.requests if isinstance(m, SendMessage) and m.chat_id == 777]
    assert "День 1: Блюдо &lt;1&gt;" in notice.text
    assert "Непонятен шаг &amp; температура" in notice.text
