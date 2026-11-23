"""Browse saved menu days and individual dishes without flooding the chat."""

from datetime import UTC, datetime

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nutrition_bot import texts
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.nutrition import day_nutrients
from nutrition_bot.db.repositories.users import Day, UserRepository
from nutrition_bot.handlers.common import callback_message
from nutrition_bot.handlers.render import html_text, render_item_html

SessionFactory = async_sessionmaker[AsyncSession]


def card(
    catalog: Catalog,
    days: list[Day],
    created: datetime,
    day: int,
    dish: int | None = None,
    notes: str = "",
) -> tuple[str, InlineKeyboardMarkup]:
    meals = days[day]
    dishes = [(meal.meal_type, item) for meal in meals for item in meal.dishes]
    prefix = f"plan:{created.strftime('%Y%m%d%H%M%S%f')}"
    rows: list[list[InlineKeyboardButton]] = []

    def button(label: str, data: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=label, callback_data=data)

    lines = [f"📅 <b>День {day + 1} из {len(days)}</b>"]
    if (datetime.now(UTC).date() - created.date()).days >= len(days):
        lines.append("<i>Этот план уже закончился.</i>")
    if dish is None:
        n = day_nutrients(catalog, meals)
        lines.append(
            f"🔥 <b>{n.kcal:.0f} ккал</b> · Б {n.protein_g:.0f}"
            f" · Ж {n.fat_g:.0f} · У {n.carb_g:.0f}"
        )
        lines.append("")
        index = 0
        for meal in meals:
            label = f"{texts.MEAL_ICONS[meal.meal_type]} {texts.MEAL_TITLES[meal.meal_type]}"
            names = ", ".join(html_text(item.name) for item in meal.dishes)
            lines.append(f"{label} — {names}")
            rows.append(
                [
                    button(
                        label if len(meal.dishes) == 1 else f"{label} · {j + 1}",
                        f"{prefix}:{day}:{index + j}",
                    )
                    for j in range(len(meal.dishes))
                ]
            )
            index += len(meal.dishes)
        nav = []
        if day > 0:
            nav.append(button("← Предыдущий день", f"{prefix}:{day - 1}"))
        if day + 1 < len(days):
            nav.append(button("Следующий день →", f"{prefix}:{day + 1}"))
        if nav:
            rows.append(nav)
        rows.extend(
            [
                [button(texts.BTN_SHOPPING, "shop:show"), button(texts.BTN_SLIP, "slip:start")],
                [button("🍽 Составить новое", "menu:start")],
            ]
        )
        if notes:
            lines.extend(("", notes))
    else:
        meal_type, item = dishes[dish]
        lines.extend((texts.MEAL_TITLES[meal_type], "", f"<b>{html_text(item.name)}</b>"))
        lines.extend(render_item_html(catalog, ingredient) for ingredient in item.items)
        if item.recipe_text:
            recipe = html_text(item.recipe_text)
            lines.extend(("", f"<blockquote expandable>{texts.RECIPE_LABEL}{recipe}</blockquote>"))
        rows.append([button("← К меню дня", f"{prefix}:{day}")])
        rows.append([button("⚠️ Сообщить о проблеме", f"{prefix}:{day}:{dish}:report")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def send_card(
    message: Message, catalog: Catalog, days: list[Day], created: datetime, *, notes: str = ""
) -> None:
    day = min(max((datetime.now(UTC).date() - created.date()).days, 0), len(days) - 1)
    text, markup = card(catalog, days, created, day, notes=notes)
    await message.answer(text, reply_markup=markup)


async def view_card(
    callback: CallbackQuery, session_factory: SessionFactory, catalog: Catalog
) -> None:
    message = callback_message(callback)
    parts = (callback.data or "").split(":")
    if message is None or len(parts) not in (3, 4):
        await callback.answer(texts.STALE_BUTTON)
        return
    saved = await load_card(session_factory, callback.from_user.id, parts)
    if saved is None:
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    text, markup = card(catalog, *saved)
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise


async def load_card(
    session_factory: SessionFactory, user_id: int, parts: list[str]
) -> tuple[list[Day], datetime, int, int | None] | None:
    """Resolve the callback against the sender's current saved plan."""
    try:
        day = int(parts[2])
        dish = int(parts[3]) if len(parts) == 4 else None
    except (IndexError, ValueError):
        return None
    async with session_factory() as session:
        saved = await UserRepository(session).get_saved_menu(user_id)
    if saved is None:
        return None
    days, created = saved
    if parts[1] != created.strftime("%Y%m%d%H%M%S%f"):
        return None
    if not 0 <= day < len(days):
        return None
    if dish is not None and not 0 <= dish < sum(len(meal.dishes) for meal in days[day]):
        return None
    return days, created, day, dish
