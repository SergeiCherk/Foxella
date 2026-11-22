"""Tests for core.metrics. Dates are fixed, so every number below was counted by hand."""

from datetime import UTC, datetime, timedelta

import pytest

from nutrition_bot.core.metrics import EventName, UsageEvent, UserFacts, overview, summarize

START = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
ONB, MENU, SLIP = EventName.ONBOARDING_DONE, EventName.MENU_RECEIVED, EventName.SLIP_PRESSED
SHOP = EventName.SHOPPING_RECEIVED


def event(user: int, name: EventName, days: float = 0.0) -> UsageEvent:
    return UsageEvent(user, name, START + timedelta(days=days))


def test_no_events_give_an_empty_summary() -> None:
    summary = summarize([], START + timedelta(days=100))
    assert summary.users == 0
    assert summary.by_event == {ONB: 0, MENU: 0, SLIP: 0, SHOP: 0}
    assert [(r.week, r.eligible, r.returned) for r in summary.returns] == [(2, 0, 0), (3, 0, 0)]


def test_people_are_counted_once_per_event_name() -> None:
    events = [
        event(1, ONB),
        event(1, MENU, 0.1),
        event(1, MENU, 0.2),  # a second menu of the same person
        event(2, ONB),
        event(2, SLIP, 1),
        event(2, SLIP, 2),
    ]
    summary = summarize(events, START + timedelta(days=3))
    assert summary.users == 2
    assert summary.by_event == {ONB: 2, MENU: 1, SLIP: 1, SHOP: 0}


@pytest.mark.parametrize(
    ("day", "week"),
    [(6.9, None), (7, 2), (13.9, 2), (14, 3), (20.9, 3), (21, None)],
)
def test_week_boundaries(day: float, week: int | None) -> None:
    """Week 2 is days 7 to <14 after the first event, week 3 is days 14 to <21."""
    events = [event(1, ONB), event(1, MENU, day)]
    summary = summarize(events, START + timedelta(days=30))
    returned = {r.week: r.returned for r in summary.returns}
    assert returned == {2: int(week == 2), 3: int(week == 3)}


def test_a_week_that_is_not_over_does_not_count_anyone() -> None:
    events = [event(1, ONB), event(1, MENU, 8)]
    summary = summarize(events, START + timedelta(days=13.9))  # week 2 ends at day 14
    assert [(r.week, r.eligible, r.returned) for r in summary.returns] == [(2, 0, 0), (3, 0, 0)]
    summary = summarize(events, START + timedelta(days=14))
    assert [(r.week, r.eligible, r.returned) for r in summary.returns] == [(2, 1, 1), (3, 0, 0)]


def test_each_person_has_their_own_first_day() -> None:
    events = [
        event(1, ONB, 0),
        event(1, MENU, 9),  # back in week 2
        event(2, ONB, 10),  # started later; week 2 for them is days 17 to 24
        event(2, MENU, 12),  # inside their week 1
    ]
    summary = summarize(events, START + timedelta(days=30))
    week2 = summary.returns[0]
    assert (week2.eligible, week2.returned) == (2, 1)


def test_a_person_with_only_week_one_activity_did_not_come_back() -> None:
    events = [event(1, ONB), event(1, MENU, 1), event(1, SLIP, 3)]
    summary = summarize(events, START + timedelta(days=60))
    assert [(r.eligible, r.returned) for r in summary.returns] == [(1, 0), (1, 0)]


def test_other_weeks_can_be_asked_for() -> None:
    events = [event(1, ONB), event(1, MENU, 22)]
    summary = summarize(events, START + timedelta(days=40), weeks=(4,))
    assert [(r.week, r.eligible, r.returned) for r in summary.returns] == [(4, 1, 1)]


@pytest.mark.parametrize("week", [1, 0, -2])
def test_week_one_and_below_make_no_sense(week: int) -> None:
    with pytest.raises(ValueError, match="start at 2"):
        summarize([], START, weeks=(week,))


def person(
    days_ago: float, goal: str = "lose", sex: str = "female", restricted: bool = False
) -> UserFacts:
    return UserFacts(NOW - timedelta(days=days_ago), goal, sex, restricted)


NOW = START + timedelta(days=40)


def test_overview_counts_new_people_in_rolling_periods() -> None:
    people = [person(0.5), person(3, "gain", "male"), person(20, restricted=True), person(39)]
    stats = overview(people, [], NOW)
    assert stats.users == 4
    assert stats.new == (1, 2, 3)  # last 24 h, 7 days, 30 days
    assert stats.goals == {"lose": 3, "gain": 1}
    assert stats.sexes == {"female": 3, "male": 1}
    assert stats.with_restrictions == 1


def test_overview_counts_active_people_and_last_week_actions() -> None:
    at = NOW - START  # event(..., days) is measured from START
    days = at.days
    events = [
        event(1, MENU, days - 0.1),  # an hour or two ago
        event(1, MENU, days - 0.2),
        event(2, SHOP, days - 3),
        event(3, SLIP, days - 10),  # active this month, not this week
        event(4, ONB, days - 35),  # outside every period
    ]
    stats = overview([], events, NOW)
    assert stats.active == (1, 2, 3)
    assert (stats.actions[MENU].times, stats.actions[MENU].people) == (2, 1)
    assert (stats.actions[SHOP].times, stats.actions[SHOP].people) == (1, 1)
    assert stats.actions[SLIP].times == 0
    assert [r.week for r in stats.returns] == [2, 3]
