"""Render example dialogs from the real handlers into ``examples/*.md``.

Run from the project root:  uv run python -m tests.render_examples

The dialogs are not written by hand: they are produced by feeding messages to the real bot with
a mocked Telegram connection and the built-in dishes (no LLM). Run it again after changing
texts, food data or norms, and the examples stay true.
"""

import asyncio
import html
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from nutrition_bot.config import Settings
from tests.integration.app_builder import bot_app
from tests.integration.bot_harness import BotHarness, Reply


def html_to_markdown(text: str) -> str:
    """Show the bot's Telegram HTML as markdown: bold, italic and the folded recipe."""
    text = re.sub(r"</?b>", "**", text)
    text = re.sub(r"</?i>", "*", text)
    text = re.sub(r"<blockquote expandable>", "▾ ", text)
    text = text.replace("<blockquote>", "│ ").replace("</blockquote>", "")
    return html.unescape(text)


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
HEADER = (
    "<!-- Создано автоматически: uv run python -m tests.render_examples. "
    "Не правьте вручную. -->\n\n"
)


@dataclass
class Transcript:
    """A dialog with the bot that records every step in Markdown."""

    app: BotHarness
    lines: list[str] = field(default_factory=list)
    last: list[Reply] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    def _label(self, data: str) -> str:
        """The text of a button the bot showed earlier in this dialog."""
        return self.labels.get(data, data)

    def _show(self, replies: list[Reply]) -> None:
        for reply in replies:
            quoted = "\n".join(
                f"> {line}" if line else ">" for line in html_to_markdown(reply.text).splitlines()
            )
            heading = "**Бот** (с картинкой Фокселы)**:**" if reply.is_photo else "**Бот:**"
            self.lines += [f"{heading}\n{quoted}", ""]
            if reply.panel:
                self.lines += [
                    "Кнопки внизу экрана: " + " · ".join(f"`{b}`" for b in reply.panel),
                    "",
                ]
            self.labels.update(zip(reply.buttons, reply.button_labels, strict=False))
            if reply.button_labels:
                self.lines += ["Кнопки: " + " · ".join(f"`{b}`" for b in reply.button_labels), ""]
        if replies:
            self.last = replies

    def note(self, text: str) -> None:
        self.lines += [f"*{text}*", ""]

    async def say(self, text: str) -> list[Reply]:
        self.lines += [f"**Вы:** {text}", ""]
        replies = await self.app.say(text)
        self._show(replies)
        return replies

    async def press(self, data: str) -> list[Reply]:
        self.lines += [f"**Вы нажали:** «{self._label(data)}»", ""]
        replies = await self.app.press(data)
        self._show(replies)
        return replies

    async def press_first_choice(self, replies: list[Reply]) -> list[Reply]:
        """Answer clarifying questions ("which chicken?") by choosing the first option."""
        while (
            replies
            and replies[-1].buttons
            and replies[-1].buttons[0].startswith(("pick:", "spick:"))
        ):
            replies = await self.press(replies[-1].buttons[0])
        return replies

    def render(self, title: str, intro: str) -> str:
        return HEADER + f"# {title}\n\n{intro}\n\n---\n\n" + "\n".join(self.lines).rstrip() + "\n"


async def onboarding(app: BotHarness) -> str:
    t = Transcript(app)
    await t.say("/start")
    await t.press("consent:ok")
    await t.press("sex:female")
    await t.say("32")
    await t.say("168")
    await t.say("64,5")
    await t.press("act:light")
    await t.press("goal:lose")
    t.note("Дальше по желанию: проверка срока. Ничего из этого не сохраняется.")
    await t.press("goalcheck:start")
    await t.say("60")
    await t.press("weeks:24")
    await t.press("goalcheck:start")
    await t.say("55")
    await t.press("weeks:4")
    return t.render(
        "Знакомство и расчёт нормы",
        "Анкета из шести вопросов. Норму калорий и БЖУ считает программа по формуле "
        "Миффлина-Сан Жеора. Нейросеть здесь не участвует. В конце бот отказывается "
        "от слишком быстрого срока и называет реалистичный.",
    )


async def menu(app: BotHarness) -> str:
    t = Transcript(app)
    await app.onboard()
    await t.say("/menu")
    await t.press("days:1")
    replies = await t.say("курица, гречка, помидоры, огурцы, яйца, творог")
    replies = await t.press_first_choice(replies)
    return t.render(
        "Меню на день",
        "Продукты пишутся обычным текстом. Если слово подходит к нескольким продуктам "
        "(например, «курица»), бот уточняет. Блюда в этом примере встроенные: без ключа "
        "нейросети бот работает на готовых рецептах. Порции в бытовых мерах, граммы не нужны.",
    )


async def shopping_and_delete(app: BotHarness) -> str:
    t = Transcript(app)
    await app.onboard()
    await app.say("/menu")
    await app.press("days:2")
    replies = await app.say("курица, гречка, помидоры, огурцы, яйца, творог, яблоки, кефир")
    while replies and replies[-1].buttons and replies[-1].buttons[0].startswith("pick:"):
        replies = await app.press(replies[-1].buttons[0])
    t.note("Меню на два дня уже составлено (оно показано в примере «Меню на день»).")
    await t.say("/shopping")
    await t.say("/profile")
    await t.say("/delete_me")
    await t.press("del:yes")
    return t.render(
        "Список покупок, профиль и удаление данных",
        "Список покупок переводит готовые блюда обратно в то, что покупают: «варёный рис» "
        "превращается в «сухой рис». То, что у вас уже есть, помечено. Все данные удаляются "
        "одной командой.",
    )


async def slip(app: BotHarness) -> str:
    t = Transcript(app)
    await app.onboard()
    await app.say("/menu")
    await app.press("days:3")
    replies = await app.say("курица, гречка, помидоры, огурцы, яйца, творог, яблоки, кефир")
    while replies and replies[-1].buttons and replies[-1].buttons[0].startswith("pick:"):
        replies = await app.press(replies[-1].buttons[0])
    t.note("Меню на три дня составлено. Теперь день прошёл не по плану.")
    await t.say("/slip")
    await t.press("slipq:large")
    return t.render(
        "Если день прошёл не по плану",
        "Превышение мягко распределяется на ближайшие дни: не больше 10 % нормы в день и "
        "никогда не ниже нижней границы калорий. Без упрёков и голода. Расчёт делает "
        "программа, тон ответа спокойный.",
    )


async def slip_with_foods(app: BotHarness) -> str:
    t = Transcript(app)
    await app.onboard()
    await app.say("/menu")
    await app.press("days:3")
    replies = await app.say("курица, гречка, помидоры, огурцы, яйца, творог, яблоки, кефир")
    while replies and replies[-1].buttons and replies[-1].buttons[0].startswith("pick:"):
        replies = await app.press(replies[-1].buttons[0])
    await t.say("/slip")
    replies = await t.say("шоколад, банан, орехи")
    replies = await t.press_first_choice(replies)
    if replies and replies[-1].buttons and replies[-1].buttons[0] == "slipc:yes":
        await t.press("slipc:yes")
    return t.render(
        "Срыв: список того, что съели",
        "Вместо грубой оценки можно написать, что съели. Бот переведёт это в калории по "
        "своей базе (а не по догадке нейросети) и спросит подтверждение.",
    )


async def main() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    EXAMPLES_DIR.mkdir(exist_ok=True)
    jobs = {
        "01-znakomstvo.md": onboarding,
        "02-menu.md": menu,
        "03-pokupki-i-udalenie.md": shopping_and_delete,
        "04-srez.md": slip,
        "05-srez-spiskom.md": slip_with_foods,
    }
    with tempfile.TemporaryDirectory() as directory:
        for number, (name, job) in enumerate(jobs.items()):
            async with bot_app(Path(directory) / f"example{number}.db", settings) as app:
                (EXAMPLES_DIR / name).write_text(await job(app), encoding="utf-8")
            print(f"examples/{name}")


if __name__ == "__main__":
    asyncio.run(main())
