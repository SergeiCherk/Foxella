"""Tests for core.slip. Default setup unless stated otherwise:

daily norm 2000 kcal, floor 1500, planned 2000 for the slip day and for each upcoming day.
Config: spread over 3 days, at most 10 % of the norm (200 kcal) per day,
ignore up to 5 % of the norm (100 kcal).
"""

import itertools

import pytest

from nutrition_bot.config import SlipConfig
from nutrition_bot.core.errors import InvalidQuantityError
from nutrition_bot.core.slip import SlipOutcome, SlipResult, plan_slip_correction

CFG = SlipConfig()
NORM = 2000.0
FLOOR = 1500.0
WEEK = [2000.0, 2000.0, 2000.0, 2000.0, 2000.0]


def plan(
    eaten: float,
    upcoming: list[float] | None = None,
    planned: float = 2000.0,
    cfg: SlipConfig = CFG,
    floor: float = FLOOR,
) -> SlipResult:
    days = WEEK if upcoming is None else upcoming
    return plan_slip_correction(eaten, planned, NORM, floor, days, cfg)


def cuts(result: SlipResult) -> list[float]:
    return [-a.delta_kcal for a in result.adjustments]


# --------------------------------------------------------- tolerance


@pytest.mark.parametrize("eaten", [2000.0, 1900.0, 2050.0, 2100.0])
def test_small_differences_are_ignored_including_the_exact_boundary(eaten: float) -> None:
    result = plan(eaten)  # tolerance = 5 % of 2000 = 100 kcal, boundary is inclusive
    assert result.outcome is SlipOutcome.WITHIN_TOLERANCE
    assert result.adjustments == ()


def test_just_above_tolerance_triggers_a_correction() -> None:
    result = plan(2101.0)
    assert result.outcome is SlipOutcome.FULL
    assert result.excess_kcal == pytest.approx(101.0)
    assert cuts(result) == pytest.approx([101 / 3] * 3)


# ---------------------------------------------------------- under plan


@pytest.mark.parametrize("eaten", [1899.0, 1500.0, 800.0, 0.0])
def test_eating_less_than_planned_never_creates_a_correction(eaten: float) -> None:
    result = plan(eaten)
    assert result.outcome is SlipOutcome.UNDER_PLAN
    assert result.adjustments == ()
    assert result.excess_kcal == 0.0


# --------------------------------------------------------- spreading


def test_excess_is_spread_evenly_over_three_days() -> None:
    result = plan(2300.0)  # excess 300 -> 100 per day, well under the 200 cap
    assert result.outcome is SlipOutcome.FULL
    assert [a.day_offset for a in result.adjustments] == [0, 1, 2]
    assert cuts(result) == pytest.approx([100.0] * 3)
    assert [a.new_planned_kcal for a in result.adjustments] == pytest.approx([1900.0] * 3)
    assert result.uncompensated_kcal == 0.0
    assert result.average_cut_kcal == pytest.approx(100.0)


def test_only_the_configured_number_of_days_is_touched() -> None:
    result = plan(2300.0, cfg=SlipConfig(spread_days=2))
    assert [a.day_offset for a in result.adjustments] == [0, 1]
    assert cuts(result) == pytest.approx([150.0, 150.0])


def test_days_beyond_the_spread_window_are_untouched() -> None:
    result = plan(2300.0)  # 5 upcoming days, only 3 are used
    assert max(a.day_offset for a in result.adjustments) == 2


# ------------------------------------------------------ daily cap (10 %)


def test_exactly_the_maximum_total_is_still_a_full_correction() -> None:
    result = plan(2600.0)  # excess 600 = 3 days * 200 cap
    assert result.outcome is SlipOutcome.FULL
    assert cuts(result) == pytest.approx([200.0] * 3)


def test_a_big_excess_is_only_partly_compensated() -> None:
    result = plan(3000.0)  # excess 1000, but at most 3 * 200
    assert result.outcome is SlipOutcome.PARTIAL
    assert cuts(result) == pytest.approx([200.0] * 3)
    assert result.excess_kcal == pytest.approx(1000.0)
    assert result.uncompensated_kcal == pytest.approx(400.0)


def test_a_binge_never_causes_more_than_the_daily_cap() -> None:
    result = plan(6000.0)  # excess 4000
    assert max(cuts(result)) <= 0.10 * NORM + 1e-9
    assert min(a.new_planned_kcal for a in result.adjustments) == pytest.approx(1800.0)
    assert result.uncompensated_kcal == pytest.approx(4000.0 - 600.0)


# --------------------------------------------------- kcal floor (never)


def test_the_floor_limits_a_day_that_is_close_to_it() -> None:
    # caps: min(200, 1550-1500)=50, min(200, 1520-1500)=20, 200. Excess 300:
    # water filling: 20, then 50, then min(200, 230) = 200 -> total 270, 30 left over.
    result = plan(2300.0, upcoming=[1550.0, 1520.0, 2000.0])
    assert result.outcome is SlipOutcome.PARTIAL
    assert cuts(result) == pytest.approx([50.0, 20.0, 200.0])
    assert [a.new_planned_kcal for a in result.adjustments] == pytest.approx(
        [1500.0, 1500.0, 1800.0]
    )
    assert result.uncompensated_kcal == pytest.approx(30.0)


def test_a_day_that_is_already_below_the_floor_is_never_lowered_further() -> None:
    result = plan(2600.0, upcoming=[1400.0, 1500.0])
    assert result.outcome is SlipOutcome.NO_ROOM
    assert result.adjustments == ()
    assert result.uncompensated_kcal == pytest.approx(600.0)


def test_floor_is_respected_when_other_days_have_room() -> None:
    result = plan(2400.0, upcoming=[1400.0, 2000.0, 2000.0])  # excess 400
    assert 0 not in [a.day_offset for a in result.adjustments]  # day 0 is below the floor
    assert cuts(result) == pytest.approx([200.0, 200.0])
    assert result.outcome is SlipOutcome.FULL


def test_cut_is_redistributed_from_capped_days_to_free_days() -> None:
    # day 0 has only 50 kcal of room; the others take more than an equal share.
    result = plan(2400.0, upcoming=[1550.0, 2000.0, 2000.0])  # excess 400
    assert cuts(result) == pytest.approx([50.0, 175.0, 175.0])
    assert result.outcome is SlipOutcome.FULL


# ------------------------------------------------------- edge cases


def test_no_upcoming_days_means_nothing_to_adjust() -> None:
    result = plan(2500.0, upcoming=[])
    assert result.outcome is SlipOutcome.NO_ROOM
    assert result.adjustments == ()
    assert result.uncompensated_kcal == pytest.approx(500.0)


def test_a_single_remaining_day_takes_what_it_can() -> None:
    assert cuts(plan(2150.0, upcoming=[2000.0])) == pytest.approx([150.0])
    one_day_big = plan(2500.0, upcoming=[2000.0])  # excess 500, cap 200
    assert one_day_big.outcome is SlipOutcome.PARTIAL
    assert cuts(one_day_big) == pytest.approx([200.0])


def test_the_slip_day_may_have_a_different_plan_than_the_norm() -> None:
    result = plan(2400.0, planned=2300.0)  # excess is measured against the plan: 100 -> ignored
    assert result.outcome is SlipOutcome.WITHIN_TOLERANCE


def test_custom_config_values_are_used() -> None:
    cfg = SlipConfig(spread_days=2, max_daily_correction=0.05, ignore_below=0.0)
    result = plan(2150.0, cfg=cfg)  # excess 150, cap 100 per day, 2 days
    assert result.outcome is SlipOutcome.FULL
    assert cuts(result) == pytest.approx([75.0, 75.0])


# ------------------------------------------------------- invalid input


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_invalid_kcal_values_are_rejected(bad: float) -> None:
    with pytest.raises(InvalidQuantityError):
        plan(bad)
    with pytest.raises(InvalidQuantityError):
        plan(2300.0, planned=bad)
    with pytest.raises(InvalidQuantityError):
        plan(2300.0, floor=bad)
    with pytest.raises(InvalidQuantityError):
        plan(2300.0, upcoming=[2000.0, bad])


@pytest.mark.parametrize("bad_norm", [0.0, -2000.0, float("nan"), float("inf")])
def test_invalid_daily_norm_is_rejected(bad_norm: float) -> None:
    with pytest.raises(InvalidQuantityError):
        plan_slip_correction(2300.0, 2000.0, bad_norm, FLOOR, WEEK, CFG)


# -------------------------------------- safety invariants on a big grid

EATEN = [0.0, 1500.0, 1950.0, 2000.0, 2101.0, 2300.0, 2600.0, 3000.0, 5000.0, 12000.0]
UPCOMING = [
    [],
    [2000.0],
    [1400.0, 1500.0],
    [1550.0, 1520.0, 2000.0],
    [2000.0, 2000.0, 2000.0, 2000.0],
    [3000.0, 1501.0, 2500.0],
    [1500.0, 1500.0, 1500.0],
]
CONFIGS = [
    CFG,
    SlipConfig(spread_days=2),
    SlipConfig(max_daily_correction=0.05),
    SlipConfig(spread_days=1),
]


@pytest.mark.parametrize(
    ("eaten", "upcoming", "cfg"), list(itertools.product(EATEN, UPCOMING, CONFIGS))
)
def test_safety_invariants(eaten: float, upcoming: list[float], cfg: SlipConfig) -> None:
    result = plan(eaten, upcoming=upcoming, cfg=cfg)
    excess = max(0.0, eaten - 2000.0)

    # never a positive "correction" (the plan is never raised) and never too many days
    assert all(a.delta_kcal < 0 for a in result.adjustments)
    assert len(result.adjustments) <= cfg.spread_days
    offsets = [a.day_offset for a in result.adjustments]
    assert offsets == sorted(set(offsets))
    assert all(o < min(cfg.spread_days, len(upcoming)) for o in offsets)

    for a in result.adjustments:
        # cap per day
        assert -a.delta_kcal <= cfg.max_daily_correction * NORM + 1e-9
        # never below the floor (these upcoming days are at or above it, or were not touched)
        assert a.new_planned_kcal >= FLOOR - 1e-9
        assert a.new_planned_kcal == pytest.approx(upcoming[a.day_offset] + a.delta_kcal)

    # never compensates more than the excess, and the bookkeeping adds up
    total = -sum(a.delta_kcal for a in result.adjustments)
    assert total <= excess + 1e-9
    if result.outcome in (SlipOutcome.FULL, SlipOutcome.PARTIAL, SlipOutcome.NO_ROOM):
        assert total + result.uncompensated_kcal == pytest.approx(result.excess_kcal)
    else:
        assert result.adjustments == ()

    # outcome is consistent with the numbers
    if result.outcome is SlipOutcome.FULL:
        assert result.uncompensated_kcal == pytest.approx(0.0, abs=1e-6)
    if result.outcome is SlipOutcome.PARTIAL:
        assert result.uncompensated_kcal > 0
        assert result.adjustments
    if result.outcome is SlipOutcome.NO_ROOM:
        assert not result.adjustments
        assert result.excess_kcal > 0


@pytest.mark.parametrize("upcoming", UPCOMING)
def test_more_eaten_never_means_less_correction(upcoming: list[float]) -> None:
    totals = [-sum(a.delta_kcal for a in plan(e, upcoming=upcoming).adjustments) for e in EATEN]
    assert totals == sorted(totals)


def test_days_with_equal_room_get_equal_cuts() -> None:
    result = plan(2330.0, upcoming=[2000.0, 2000.0, 2000.0])
    assert max(cuts(result)) - min(cuts(result)) < 1e-9


# --------------------------------------------------------- several slips, "instead", menu day


def test_an_earlier_cut_counts_against_the_daily_cap() -> None:
    from nutrition_bot.core.slip import merge_adjustments

    first = plan(2600.0)  # 600 over: 200 off each of 3 days, the cap
    before = merge_adjustments([], first, 3)
    assert before == [-200.0, -200.0, -200.0]
    second = plan_slip_correction(
        2500.0, 2000.0, NORM, FLOOR, [NORM + d for d in before], CFG, already_cut=[200.0] * 3
    )
    assert second.outcome is SlipOutcome.NO_ROOM  # the days are already at the cap
    assert merge_adjustments(before, second, 3) == before


def test_a_second_slip_adds_to_the_first() -> None:
    from nutrition_bot.core.slip import merge_adjustments

    before = merge_adjustments([], plan(2300.0), 3)  # 300 over: 100 a day
    second = plan_slip_correction(
        2300.0, 2000.0, NORM, FLOOR, [NORM + d for d in before], CFG, already_cut=[100.0] * 3
    )
    assert merge_adjustments(before, second, 3) == pytest.approx([-200.0, -200.0, -200.0])


def test_merge_pads_and_ignores_days_beyond_the_window() -> None:
    from nutrition_bot.core.slip import DayAdjustment, merge_adjustments

    result = SlipResult(
        SlipOutcome.FULL, 50.0, (DayAdjustment(0, -30.0, 0), DayAdjustment(5, -20.0, 0)), 0
    )
    assert merge_adjustments([-10.0], result, 2) == [-40.0, 0.0]


def test_eaten_instead_of_a_meal_takes_that_meal_off() -> None:
    from nutrition_bot.core.slip import eaten_today_kcal

    assert eaten_today_kcal(2000.0, 900.0) == 2900.0  # on top of the plan
    assert eaten_today_kcal(2000.0, 900.0, replaced_kcal=700.0) == 2200.0
    assert eaten_today_kcal(500.0, 100.0, replaced_kcal=700.0) == 100.0  # never below zero
    with pytest.raises(InvalidQuantityError):
        eaten_today_kcal(2000.0, -1.0)


def test_the_menu_day_is_found_by_date() -> None:
    from datetime import date

    from nutrition_bot.core.slip import menu_day_index

    made = date(2026, 11, 20)
    assert menu_day_index(made, date(2026, 11, 20), 3) == 0
    assert menu_day_index(made, date(2026, 11, 22), 3) == 2
    assert menu_day_index(made, date(2026, 11, 23), 3) is None  # the menu is over
    assert menu_day_index(made, date(2026, 11, 19), 3) is None  # clock went back
