"""Gentle recalculation after eating off-plan. Pure functions, no I/O.

Iron rule: a correction is spread over the next days, capped to a share of the daily norm per
day, and never lowers a day below the kcal floor. Whatever cannot be compensated within these
limits is simply left alone: the plan is never tightened further to "pay back" an excess.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from nutrition_bot.config import SlipConfig
from nutrition_bot.core.errors import InvalidQuantityError
from nutrition_bot.core.models import DailyNorm, Nutrients

EPS = 1e-6


class SlipOutcome(StrEnum):
    """What the bot should tell the user."""

    WITHIN_TOLERANCE = "within_tolerance"  # difference is small: change nothing
    UNDER_PLAN = "under_plan"  # ate clearly less than planned: nothing to compensate
    FULL = "full"  # the whole excess was spread over the next days
    PARTIAL = "partial"  # only part was compensated (caps or the kcal floor)
    NO_ROOM = "no_room"  # excess, but no day can be lowered at all


@dataclass(frozen=True, slots=True)
class DayAdjustment:
    """Change to one upcoming day. ``day_offset`` 0 is the first day after the slip."""

    day_offset: int
    delta_kcal: float  # negative: the day's plan is reduced by this much
    new_planned_kcal: float


@dataclass(frozen=True, slots=True)
class SlipResult:
    """Result of a slip calculation."""

    outcome: SlipOutcome
    excess_kcal: float  # how much more than planned was eaten (0 if not more)
    adjustments: tuple[DayAdjustment, ...]
    uncompensated_kcal: float  # the part of the excess that is deliberately left alone

    @property
    def average_cut_kcal(self) -> float:
        """Average reduction per adjusted day (0 when there are no adjustments)."""
        if not self.adjustments:
            return 0.0
        return -sum(a.delta_kcal for a in self.adjustments) / len(self.adjustments)


def _check_kcal(value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise InvalidQuantityError(value)


def _spread(amount: float, caps: Sequence[float]) -> list[float]:
    """Split ``amount`` as evenly as possible without exceeding any cap ("water filling").

    The result sums to ``min(amount, sum(caps))``.
    """
    result = [0.0] * len(caps)
    remaining = amount
    order = sorted(range(len(caps)), key=lambda i: caps[i])
    for rank, index in enumerate(order):
        take = min(caps[index], remaining / (len(order) - rank))
        result[index] = take
        remaining -= take
    return result


def plan_slip_correction(
    eaten_kcal: float,
    planned_kcal: float,
    daily_norm_kcal: float,
    floor_kcal: float,
    upcoming_planned_kcal: Sequence[float],
    cfg: SlipConfig,
    already_cut: Sequence[float] = (),
) -> SlipResult:
    """Decide how to adjust the next days after a day that differed from the plan.

    ``upcoming_planned_kcal`` holds the planned kcal of the days after the slip, in order,
    with earlier corrections already applied. ``already_cut`` (kcal, positive) is what earlier
    slips took from each of those days: together with the new cut it stays within the daily cap.
    Raises ``InvalidQuantityError`` for negative or non-finite kcal values.
    """
    for value in (eaten_kcal, planned_kcal, floor_kcal, *upcoming_planned_kcal, *already_cut):
        _check_kcal(value)
    if not math.isfinite(daily_norm_kcal) or daily_norm_kcal <= 0:
        raise InvalidQuantityError(daily_norm_kcal)

    diff = eaten_kcal - planned_kcal
    tolerance = cfg.ignore_below * daily_norm_kcal
    if abs(diff) <= tolerance:
        return SlipResult(SlipOutcome.WITHIN_TOLERANCE, max(diff, 0.0), (), 0.0)
    if diff < 0:
        return SlipResult(SlipOutcome.UNDER_PLAN, 0.0, (), 0.0)

    days = list(upcoming_planned_kcal[: cfg.spread_days])
    daily_cap = cfg.max_daily_correction * daily_norm_kcal
    taken = [already_cut[i] if i < len(already_cut) else 0.0 for i in range(len(days))]
    caps = [
        max(0.0, min(daily_cap - cut, planned - floor_kcal))
        for planned, cut in zip(days, taken, strict=True)
    ]
    cuts = _spread(diff, caps)

    adjustments = tuple(
        DayAdjustment(offset, -cut, days[offset] - cut)
        for offset, cut in enumerate(cuts)
        if cut > EPS
    )
    uncompensated = max(0.0, diff - sum(cuts))
    if not adjustments:
        outcome = SlipOutcome.NO_ROOM
    elif uncompensated <= EPS:
        outcome = SlipOutcome.FULL
    else:
        outcome = SlipOutcome.PARTIAL
    return SlipResult(outcome, diff, adjustments, uncompensated)


def eaten_today_kcal(planned_kcal: float, extra_kcal: float, replaced_kcal: float = 0.0) -> float:
    """What the day came to: the plan, minus a meal that was skipped for this food, plus it."""
    for value in (planned_kcal, extra_kcal, replaced_kcal):
        _check_kcal(value)
    return max(0.0, planned_kcal - replaced_kcal) + extra_kcal


def merge_adjustments(existing: Sequence[float], result: SlipResult, days: int) -> list[float]:
    """Earlier corrections plus the new ones, one number per upcoming day (``days`` long).

    A second slip on the same day adds to the first instead of replacing it.
    """
    merged = [existing[i] if i < len(existing) else 0.0 for i in range(days)]
    for adjustment in result.adjustments:
        if adjustment.day_offset < days:
            merged[adjustment.day_offset] += adjustment.delta_kcal
    return merged


def menu_day_index(created_on: date, today: date, days: int) -> int | None:
    """Which day of a menu made on ``created_on`` is ``today`` (0-based), ``None`` if none.

    A menu starts on the day it is made; after its last day there is no plan to compare with.
    """
    index = (today - created_on).days
    return index if 0 <= index < days else None


def apply_adjustment(norm: DailyNorm, delta_kcal: float) -> Nutrients:
    """The daily target after a correction: kcal moved by ``delta_kcal``, never below the floor.

    Macros are scaled by the same ratio, so the proportions of the plan stay as they were.
    """
    if not math.isfinite(delta_kcal):
        raise InvalidQuantityError(delta_kcal)
    target = norm.target
    kcal = max(norm.floor_kcal, target.kcal + delta_kcal)
    ratio = kcal / target.kcal
    return Nutrients(
        kcal=kcal,
        protein_g=target.protein_g * ratio,
        fat_g=target.fat_g * ratio,
        carb_g=target.carb_g * ratio,
        fiber_g=target.fiber_g * ratio,
    )
