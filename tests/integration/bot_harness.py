"""A fake Telegram: real dispatcher, real handlers, real database, no network.

``MockedSession`` records every request the bot would send; ``BotHarness`` feeds updates in
(messages and button presses) and returns what the bot answered.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, SendPhoto, TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot.core.measures import Catalog


class MockedSession(BaseSession):
    """Collects the bot's requests instead of sending them."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        """Nothing to close."""

    async def stream_content(  # type: ignore[override,misc]
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[bytes, None]:
        """Files are never downloaded in tests."""
        yield b""

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        """Record the request; answer messages with a Message, everything else with ``True``."""
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message.model_validate(
                {
                    "message_id": len(self.requests),
                    "date": int(datetime.now(UTC).timestamp()),
                    "chat": {"id": method.chat_id, "type": "private"},
                    "text": method.text,
                },
                context={"bot": bot},
            )
        if isinstance(method, SendPhoto):
            return Message.model_validate(
                {
                    "message_id": len(self.requests),
                    "date": int(datetime.now(UTC).timestamp()),
                    "chat": {"id": method.chat_id, "type": "private"},
                    "caption": method.caption,
                    "photo": [
                        {"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90},
                        {"file_id": "FILE-ID", "file_unique_id": "b", "width": 800, "height": 800},
                    ],
                },
                context={"bot": bot},
            )
        return True


@dataclass(frozen=True)
class Reply:
    """One message the bot sent: its text and the callback data of its buttons."""

    text: str
    buttons: tuple[str, ...] = ()
    button_labels: tuple[str, ...] = ()
    panel: tuple[str, ...] = ()  # labels of the permanent reply keyboard, if this message sets it
    is_photo: bool = False


@dataclass
class BotHarness:
    """Feeds updates to the dispatcher and reports the answers."""

    dispatcher: Dispatcher
    bot: Bot
    session_factory: async_sessionmaker[AsyncSession]
    catalog: Catalog
    _seen: int = 0
    _counter: int = field(default=0)

    @property
    def session(self) -> MockedSession:
        """The recording session of the bot."""
        assert isinstance(self.bot.session, MockedSession)
        return self.bot.session

    def _message(self, user_id: int, text: str) -> dict[str, Any]:
        self._counter += 1
        message: dict[str, Any] = {
            "message_id": self._counter,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "text": text,
        }
        if text.startswith("/"):
            message["entities"] = [
                {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
            ]
        return message

    async def _feed(self, payload: dict[str, Any]) -> list[Reply]:
        self._counter += 1
        update = Update.model_validate(
            {"update_id": self._counter, **payload}, context={"bot": self.bot}
        )
        await self.dispatcher.feed_update(self.bot, update)
        return self._new_replies()

    def _new_replies(self) -> list[Reply]:
        replies: list[Reply] = []
        for method in self.session.requests[self._seen :]:
            if not isinstance(method, SendMessage | SendPhoto):
                continue
            markup = method.reply_markup
            data: list[str] = []
            labels: list[str] = []
            panel: list[str] = []
            if isinstance(markup, ReplyKeyboardMarkup):
                panel = [button.text for row in markup.keyboard for button in row]
            if isinstance(markup, InlineKeyboardMarkup):
                for row in markup.inline_keyboard:
                    for button in row:
                        data.append(button.callback_data or "")
                        labels.append(button.text)
            text = method.caption if isinstance(method, SendPhoto) else method.text
            replies.append(
                Reply(
                    text or "",
                    tuple(data),
                    tuple(labels),
                    tuple(panel),
                    isinstance(method, SendPhoto),
                )
            )
        self._seen = len(self.session.requests)
        return replies

    async def say(self, text: str, user_id: int = 1) -> list[Reply]:
        """The user writes a message (a command if it starts with a slash)."""
        return await self._feed({"message": self._message(user_id, text)})

    async def press(self, data: str, user_id: int = 1) -> list[Reply]:
        """The user presses an inline button with this callback data."""
        return await self._feed(
            {
                "callback_query": {
                    "id": str(self._counter),
                    "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
                    "chat_instance": "test",
                    "data": data,
                    "message": self._message(user_id, "old message"),
                }
            }
        )

    async def onboard(self, user_id: int = 1, goal: str = "lose") -> list[Reply]:
        """The whole onboarding with typical answers; returns the final replies."""
        await self.say("/start", user_id)
        await self.press("consent:ok", user_id)
        await self.press("sex:female", user_id)
        await self.say("32", user_id)
        await self.say("168", user_id)
        await self.say("64,5", user_id)
        await self.press("act:light", user_id)
        return await self.press(f"goal:{goal}", user_id)
