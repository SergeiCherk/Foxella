"""Reviews and complaints are delivered to configured bot owners."""

from aiogram.methods import SendMessage

from nutrition_bot import texts
from nutrition_bot.config import Settings
from tests.integration.conftest import AppFactory

ADMIN = 777


def feedback_settings(settings: Settings, admins: str = str(ADMIN)) -> Settings:
    ids = frozenset(int(item) for item in admins.split(",") if item)
    return settings.model_copy(update={"admin_ids": ids})


async def test_review_is_sent_to_the_owner(make_app: AppFactory, settings: Settings) -> None:
    app = await make_app(use=feedback_settings(settings))
    await app.say(texts.BTN_NAV_FEEDBACK, user_id=42)
    (prompt,) = await app.press("feedback:review", user_id=42)

    assert texts.FEEDBACK_ASK_REVIEW in prompt.text
    replies = await app.say("Очень удобно <и красиво>", user_id=42)

    assert replies[-1].text == texts.FEEDBACK_SENT
    delivered = [r for r in app.session.requests if isinstance(r, SendMessage)]
    owner_message = delivered[-2]
    assert owner_message.chat_id == ADMIN
    assert "Очень удобно &lt;и красиво&gt;" in owner_message.text
    assert "<code>42</code>" in owner_message.text


async def test_complaint_can_be_cancelled(make_app: AppFactory, settings: Settings) -> None:
    app = await make_app(use=feedback_settings(settings))
    await app.say("/feedback", user_id=42)
    await app.press("feedback:complaint", user_id=42)
    (cancelled,) = await app.press("feedback:cancel", user_id=42)

    assert cancelled.text == texts.FEEDBACK_CANCELLED
    (fallback,) = await app.say("Это уже обычное сообщение", user_id=42)
    assert fallback.text == texts.FALLBACK


async def test_feedback_is_unavailable_without_an_admin(
    make_app: AppFactory, settings: Settings
) -> None:
    app = await make_app(use=feedback_settings(settings, admins=""))
    await app.say("/feedback", user_id=42)
    await app.press("feedback:review", user_id=42)
    (reply,) = await app.say("Текст отзыва", user_id=42)

    assert reply.text == texts.FEEDBACK_UNAVAILABLE
