"""Beta usage metrics: how many people did what, and who came back. Pure functions, no I/O.

An event holds only a person's id, a fixed event name and a time. No message text is ever part
of it. Week 1 is the first seven days after a person's first event, week 2 the next seven, and so
on. A person "came back in week N" if there is any event in that week.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

DAYS_PER_WEEK = 7
RETURN_WEEKS = (2, 3)  # the weeks in which "did they come back?" is measured


class EventName(StrEnum):
    """The only things the bot counts. Stored as text, so never rename an existing value."""

    ONBOARDING_DONE = "onboarding_done"  # a new person finished the questions
    MENU_RECEIVED = "menu_received"  # a menu was built and sent
    SLIP_PRESSED = "slip_pressed"  # the person started the "ate something else" flow
    SHOPPING_RECEIVED = "shopping_received"  # a shopping list was built and sent


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """One event. ``at`` must be timezone-aware."""

    user_id: int
    name: EventName
    at: datetime


@dataclass(frozen=True, slots=True)
class WeekReturn:
    """How many people came back in a week. Only people whose week is over are counted."""

    week: int
    eligible: int  # people whose week ``week`` has fully passed
    returned: int  # of those, people with at least one event in that week


@dataclass(frozen=True, slots=True)
class BetaSummary:
    """Counts of people (never of events): each person is counted once per line."""

    users: int
    by_event: dict[EventName, int]
    returns: tuple[WeekReturn, ...]


def summarize(
    events: Iterable[UsageEvent], now: datetime, weeks: Sequence[int] = RETURN_WEEKS
) -> BetaSummary:
    """Count people per event and the share that came back in each of ``weeks``.

    The week of a person starts at their first event of any kind. A person is counted for a
    week only once that week is over (``now`` is passed in, so the result is reproducible).
    Raises ``ValueError`` for a week below 2: week 1 is the first visit itself.
    """
    if any(week < 2 for week in weeks):
        raise ValueError("weeks start at 2: week 1 is the first visit itself")
    by_user: dict[int, list[UsageEvent]] = defaultdict(list)
    for event in events:
        by_user[event.user_id].append(event)

    people_by_event: dict[EventName, set[int]] = {name: set() for name in EventName}
    first_seen: dict[int, datetime] = {}
    for user_id, items in by_user.items():
        first_seen[user_id] = min(item.at for item in items)
        for item in items:
            people_by_event[item.name].add(user_id)

    returns: list[WeekReturn] = []
    for week in weeks:
        eligible = returned = 0
        for user_id, items in by_user.items():
            start = first_seen[user_id]
            week_start = start + timedelta(days=(week - 1) * DAYS_PER_WEEK)
            week_end = start + timedelta(days=week * DAYS_PER_WEEK)
            if now < week_end:
                continue
            eligible += 1
            if any(week_start <= item.at < week_end for item in items):
                returned += 1
        returns.append(WeekReturn(week, eligible, returned))

    return BetaSummary(
        users=len(by_user),
        by_event={name: len(people) for name, people in people_by_event.items()},
        returns=tuple(returns),
    )


PERIOD_DAYS = (1, 7, 30)  # "today", "this week", "this month" of the admin overview (rolling)
ACTIONS_DAYS = 7  # actions in the overview are counted over the last week


@dataclass(frozen=True, slots=True)
class UserFacts:
    """What the admin overview needs of one person: no id, no profile numbers."""

    created_at: datetime  # timezone-aware
    goal: str
    sex: str
    has_restrictions: bool


@dataclass(frozen=True, slots=True)
class ActionCount:
    """How often something happened in the last week and how many people did it."""

    times: int
    people: int


@dataclass(frozen=True, slots=True)
class Overview:
    """Aggregates for the bot owner. Only counts, never anything that points to a person."""

    users: int
    new: tuple[int, ...]  # people who joined in each of ``PERIOD_DAYS``
    active: tuple[int, ...]  # people with an event in each of ``PERIOD_DAYS``
    actions: dict[EventName, ActionCount]  # over the last ``ACTIONS_DAYS``
    goals: dict[str, int]
    sexes: dict[str, int]
    with_restrictions: int
    returns: tuple[WeekReturn, ...]


def overview(users: Iterable[UserFacts], events: Sequence[UsageEvent], now: datetime) -> Overview:
    """Count people and actions for the admin panel; ``now`` is passed in for reproducibility.

    Periods are rolling ("the last 24 hours", "the last 7 days"), so the numbers do not depend
    on the time zone of the person reading them.
    """
    people = list(users)
    starts = [now - timedelta(days=days) for days in PERIOD_DAYS]
    week_start = now - timedelta(days=ACTIONS_DAYS)
    actions: dict[EventName, ActionCount] = {}
    for name in EventName:
        recent = [e for e in events if e.name is name and e.at >= week_start]
        actions[name] = ActionCount(len(recent), len({e.user_id for e in recent}))
    goals: dict[str, int] = defaultdict(int)
    sexes: dict[str, int] = defaultdict(int)
    for person in people:
        goals[person.goal] += 1
        sexes[person.sex] += 1
    return Overview(
        users=len(people),
        new=tuple(sum(p.created_at >= start for p in people) for start in starts),
        active=tuple(len({e.user_id for e in events if e.at >= start}) for start in starts),
        actions=actions,
        goals=dict(goals),
        sexes=dict(sexes),
        with_restrictions=sum(p.has_restrictions for p in people),
        returns=summarize(events, now).returns,
    )
