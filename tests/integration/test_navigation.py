"""The greeting picture and the permanent button panel."""

from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import FSInputFile, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from nutrition_bot import texts
from nutrition_bot.config import WELCOME_IMAGE
from tests.integration.bot_harness import BotHarness


def test_the_greeting_picture_is_shipped_with_the_package() -> None:
    assert WELCOME_IMAGE.is_file()
    assert WELCOME_IMAGE.stat().st_size < 10 * 1024 * 1024  # Telegram's photo limit


async def test_start_greets_with_a_picture_then_asks_the_first_question(app: BotHarness) -> None:
    replies = await app.say("/start")
    assert replies[0].is_photo
    assert replies[0].text == f"{texts.START}\n\n{texts.DISCLAIMER}"
    assert len(replies[0].text) <= 1024  # a photo caption is limited
    assert replies[0].buttons == ("consent:ok",)
    assert (await app.press("consent:ok"))[-1].text == texts.ASK_SEX


async def test_greeting_falls_back_to_text_without_the_picture(
    app: BotHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("nutrition_bot.handlers.onboarding.WELCOME_IMAGE", tmp_path / "none.jpg")
    replies = await app.say("/start")
    assert not replies[0].is_photo
    assert texts.DISCLAIMER in replies[0].text
    assert replies[0].buttons == ("consent:ok",)


async def test_greeting_falls_back_to_text_if_telegram_rejects_the_picture(
    app: BotHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(self: Message, *args: object, **kwargs: object) -> None:
        raise TelegramBadRequest(method=SendPhoto(chat_id=1, photo="x"), message="bad picture")

    monkeypatch.setattr(Message, "answer_photo", refuse)
    replies = await app.say("/start")
    assert not replies[0].is_photo
    assert texts.START in replies[0].text
    assert replies[0].buttons == ("consent:ok",)


async def test_onboarding_sets_the_panel_just_before_the_result(app: BotHarness) -> None:
    await app.onboard()
    sent = [m for m in app.session.requests if isinstance(m, SendMessage)]
    hint = next(m for m in sent if m.text == texts.NAV_HINT)
    assert isinstance(hint.reply_markup, ReplyKeyboardMarkup)
    assert [b.text for row in hint.reply_markup.keyboard for b in row] == list(texts.NAV_LABELS)
    assert "Готово!" in sent[-1].text  # the result with its own buttons comes last
    assert sent.index(hint) == len(sent) - 2


async def test_the_panel_has_the_four_labels(app: BotHarness) -> None:
    replies = await app.onboard()
    assert replies  # onboarding finished
    welcome = await app.say("/start")
    assert welcome[-1].text == texts.WELCOME_BACK
    assert welcome[-1].panel == texts.NAV_LABELS


@pytest.mark.parametrize(
    ("label", "command"),
    [
        (texts.BTN_NAV_MENU, "/menu"),
        (texts.BTN_NAV_SHOPPING, "/shopping"),
        (texts.BTN_NAV_SLIP, "/slip"),
        (texts.BTN_NAV_PROFILE, "/profile"),
    ],
)
async def test_each_panel_button_does_what_its_command_does(
    app: BotHarness, label: str, command: str
) -> None:
    await app.onboard()
    by_command = [(r.text, r.buttons) for r in await app.say(command)]
    by_button = [(r.text, r.buttons) for r in await app.say(label)]
    assert by_button == by_command


async def test_a_panel_button_in_the_middle_of_onboarding_is_not_taken_as_an_answer(
    app: BotHarness,
) -> None:
    await app.say("/start")
    await app.press("sex:female")
    replies = await app.say(texts.BTN_NAV_PROFILE)
    assert replies[-1].text == texts.NEED_PROFILE
    assert (await app.say("32"))[-1].text == texts.FALLBACK  # the conversation was left


async def test_a_panel_button_is_not_taken_as_a_product_list(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/menu")
    await app.press("days:1")
    replies = await app.say(texts.BTN_NAV_SHOPPING)
    assert "День 1" not in "\n".join(r.text for r in replies)
    assert (await app.say("привет"))[-1].text == texts.FALLBACK


async def test_deleting_the_data_removes_the_panel(app: BotHarness) -> None:
    await app.onboard()
    await app.say("/delete_me")
    app.session.requests.clear()
    await app.press("del:yes")
    sent = [m for m in app.session.requests if isinstance(m, SendMessage)]
    assert sent[-1].text == texts.DELETE_DONE
    assert isinstance(sent[-1].reply_markup, ReplyKeyboardRemove)


def _photo_requests(app: BotHarness) -> list[SendPhoto]:
    return [r for r in app.session.requests if isinstance(r, SendPhoto)]


async def test_the_picture_is_uploaded_once_and_then_sent_by_file_id(app: BotHarness) -> None:
    await app.say("/start", user_id=1)
    await app.say("/start", user_id=2)
    first, second = _photo_requests(app)
    assert isinstance(first.photo, FSInputFile)
    assert second.photo == "FILE-ID"  # the id Telegram returned for the biggest size
    assert second.caption == first.caption
    assert second.reply_markup == first.reply_markup


async def test_a_refused_file_id_is_forgotten_and_the_picture_uploaded_again(
    app: BotHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await app.say("/start", user_id=1)
    real = Message.answer_photo
    calls = 0

    async def stale_id(self: Message, photo: object, *args: object, **kwargs: object) -> Message:
        nonlocal calls
        calls += 1
        if isinstance(photo, str):
            raise TelegramBadRequest(method=SendPhoto(chat_id=1, photo="x"), message="wrong id")
        return await real(self, photo, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Message, "answer_photo", stale_id)
    replies = await app.say("/start", user_id=2)
    assert replies[0].is_photo
    assert calls == 2  # the stale id was tried, then the file was uploaded
    assert isinstance(_photo_requests(app)[-1].photo, FSInputFile)
    monkeypatch.setattr(Message, "answer_photo", real)
    await app.say("/start", user_id=3)
    assert _photo_requests(app)[-1].photo == "FILE-ID"  # remembered again after the upload
