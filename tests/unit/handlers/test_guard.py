"""Tests for the anti-spam guard (a fake clock makes the pauses exact)."""

import pytest

from nutrition_bot.handlers import guard as guard_module
from nutrition_bot.handlers.guard import MenuGuard


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(cooldown: float = 30.0) -> tuple[MenuGuard, Clock]:
    clock = Clock()
    return MenuGuard(cooldown, clock), clock


def test_the_first_build_is_allowed() -> None:
    guard, _ = make()
    verdict = guard.acquire(1)
    assert verdict.allowed
    assert not verdict.busy


def test_a_second_build_while_the_first_runs_is_refused_as_busy() -> None:
    guard, _ = make()
    guard.acquire(1)
    verdict = guard.acquire(1)
    assert not verdict.allowed
    assert verdict.busy


def test_users_do_not_block_each_other() -> None:
    guard, _ = make()
    assert guard.acquire(1).allowed
    assert guard.acquire(2).allowed
    assert not guard.acquire(1).allowed


def test_after_release_the_cooldown_applies_with_the_exact_remaining_time() -> None:
    guard, clock = make(30.0)
    guard.acquire(1)
    guard.release(1)
    clock.now += 10
    verdict = guard.acquire(1)
    assert not verdict.allowed
    assert not verdict.busy
    assert verdict.wait_s == pytest.approx(20.0)


def test_the_cooldown_boundary_is_inclusive() -> None:
    guard, clock = make(30.0)
    guard.acquire(1)
    guard.release(1)
    clock.now += 29.999
    assert not guard.acquire(1).allowed
    clock.now += 0.001
    assert guard.acquire(1).allowed


def test_a_zero_cooldown_only_prevents_parallel_builds() -> None:
    guard, _ = make(0.0)
    assert guard.acquire(1).allowed
    assert guard.acquire(1).busy
    guard.release(1)
    assert guard.acquire(1).allowed


def test_release_without_acquire_is_harmless() -> None:
    guard, _ = make()
    guard.release(7)
    assert not guard.acquire(7).allowed  # it still starts a cooldown, never a stuck "busy"


def test_release_always_frees_the_user() -> None:
    guard, clock = make(5.0)
    guard.acquire(1)
    guard.release(1)
    clock.now += 5
    assert guard.acquire(1).allowed


def test_old_entries_are_forgotten_when_the_table_grows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_module, "PRUNE_ABOVE", 3)
    guard, clock = make(10.0)
    for user in range(4):
        guard.acquire(user)
        guard.release(user)
    clock.now += 11  # all four cooldowns are over
    guard.acquire(99)
    guard.release(99)  # the table is above the limit: finished users are dropped
    assert set(guard._finished_at) == {99}
    assert guard.acquire(0).allowed
