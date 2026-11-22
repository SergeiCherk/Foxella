"""Inline keyboards. Callback data is short ``prefix:value`` text, parsed by the handlers."""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from nutrition_bot import texts
from nutrition_bot.core.models import ActivityLevel, Goal, Sex


def _build(rows: Sequence[Sequence[tuple[str, str]]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        for label, data in row:
            builder.button(text=label, callback_data=data)
    builder.adjust(*[len(row) for row in rows])
    return builder.as_markup()


def main_keyboard() -> ReplyKeyboardMarkup:
    """The permanent panel under the input field: the four things people do most."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_NAV_MENU), KeyboardButton(text=texts.BTN_NAV_SHOPPING)],
            [KeyboardButton(text=texts.BTN_NAV_SLIP), KeyboardButton(text=texts.BTN_NAV_PROFILE)],
            [KeyboardButton(text=texts.BTN_NAV_FEEDBACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def consent_keyboard() -> InlineKeyboardMarkup:
    """The single "Понятно" button under the disclaimer."""
    return _build([[(texts.BTN_CONSENT, "consent:ok")]])


def sex_keyboard() -> InlineKeyboardMarkup:
    """Choice of sex."""
    return _build([[(texts.SEX_LABELS[s], f"sex:{s.value}") for s in Sex]])


def activity_keyboard() -> InlineKeyboardMarkup:
    """Choice of activity level, one level per row."""
    return _build([[(texts.ACTIVITY_LABELS[a], f"act:{a.value}")] for a in ActivityLevel])


def goal_keyboard() -> InlineKeyboardMarkup:
    """Choice of goal."""
    return _build([[(texts.GOAL_LABELS[g], f"goal:{g.value}")] for g in Goal])


def _goal_rows(goal: Goal | None) -> list[list[tuple[str, str]]]:
    """The "check my term" button, only for goals that change weight."""
    if goal in (Goal.LOSE, Goal.GAIN):
        return [[(texts.BTN_CHECK_GOAL, "goalcheck:start")]]
    return []


def after_onboarding_keyboard(
    goal: Goal | None = None, with_restrictions: bool = False
) -> InlineKeyboardMarkup:
    """The obvious next step after the norm is shown (or after a correction: menu only)."""
    rows = [[(texts.BTN_MAKE_MENU, "menu:start")], *_goal_rows(goal)]
    if with_restrictions:
        rows.append([(texts.BTN_RESTRICTIONS, "diet:show")])
    return _build(rows)


def restrictions_keyboard(codes: Sequence[str], selected: Sequence[str]) -> InlineKeyboardMarkup:
    """One toggle per restriction (✅ when on) and "Готово"."""
    rows = [
        [
            (
                (texts.RESTRICTION_ON if code in selected else texts.RESTRICTION_OFF).format(
                    label=texts.RESTRICTION_LABELS.get(code, code)
                ),
                f"diet:t:{code}",
            )
        ]
        for code in codes
    ]
    rows.append([(texts.BTN_RESTRICTIONS_DONE, "diet:done")])
    return _build(rows)


def weeks_keyboard(options: Sequence[int]) -> InlineKeyboardMarkup:
    """Typical terms for the target weight check."""
    return _build([[(texts.WEEKS_LABEL.format(n=n), f"weeks:{n}") for n in options]])


def days_keyboard(options: Sequence[int]) -> InlineKeyboardMarkup:
    """Number of days to plan."""
    return _build([[(texts.DAYS_LABELS[n], f"days:{n}") for n in options]])


def products_keyboard(has_previous: bool) -> InlineKeyboardMarkup:
    """Shortcuts under the question about products."""
    rows = [[(texts.BTN_ANY_PRODUCTS, "pantry:any")]]
    if has_previous:
        rows.append([(texts.BTN_LAST_PRODUCTS, "pantry:last")])
    return _build(rows)


def clarify_keyboard(
    prefix: str, options: Sequence[tuple[int, str]], skip_label: str
) -> InlineKeyboardMarkup:
    """Buttons for an ambiguous phrase: one per food, "any of them" and "skip"."""
    rows = [[(name, f"{prefix}:{food_id}")] for food_id, name in options]
    rows.append([(texts.MENU_CLARIFY_ANY, f"{prefix}:all"), (skip_label, f"{prefix}:skip")])
    return _build(rows)


def after_menu_keyboard() -> InlineKeyboardMarkup:
    """Next steps under a finished menu."""
    return _build([[(texts.BTN_SHOPPING, "shop:show")], [(texts.BTN_SLIP, "slip:start")]])


def slip_quick_keyboard() -> InlineKeyboardMarkup:
    """Rough sizes for people who do not want to list foods."""
    return _build([[(label, f"slipq:{key}")] for key, label in texts.SLIP_QUICK_LABELS.items()])


def slip_confirm_keyboard() -> InlineKeyboardMarkup:
    """On top of the plan, instead of one meal, or start over."""
    instead = [
        (label, f"slipc:instead:{meal.value}") for meal, label in texts.SLIP_INSTEAD_LABELS.items()
    ]
    return _build(
        [
            [(texts.BTN_SLIP_EXTRA, "slipc:yes")],
            instead[:2],
            instead[2:],
            [(texts.BTN_REDO, "slipc:redo")],
        ]
    )


def profile_keyboard(goal: Goal | None = None) -> InlineKeyboardMarkup:
    """Actions under the profile."""
    return _build(
        [
            [(texts.BTN_EDIT_PROFILE, "profile:edit")],
            *_goal_rows(goal),
            [(texts.BTN_RESTRICTIONS, "diet:show")],
            [(texts.BTN_DELETE, "del:ask")],
        ]
    )


def delete_keyboard() -> InlineKeyboardMarkup:
    """Confirmation of /delete_me."""
    return _build([[(texts.BTN_YES_DELETE, "del:yes"), (texts.BTN_CANCEL, "del:no")]])


def admin_keyboard() -> InlineKeyboardMarkup:
    """Under the /admin statistics."""
    return _build([[(texts.BTN_ADMIN_REFRESH, "admin:refresh")]])


def feedback_keyboard() -> InlineKeyboardMarkup:
    """Choose a review, a complaint, or cancel."""
    return _build(
        [
            [(texts.FEEDBACK_REVIEW, "feedback:review")],
            [(texts.FEEDBACK_COMPLAINT, "feedback:complaint")],
            [(texts.FEEDBACK_CANCEL, "feedback:cancel")],
        ]
    )


def feedback_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel while the person is writing a feedback message."""
    return _build([[(texts.FEEDBACK_CANCEL, "feedback:cancel")]])
