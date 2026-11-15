"""Protection of the paid LLM from button spamming: one menu build per user at a time."""

import time
from collections.abc import Callable
from dataclasses import dataclass

PRUNE_ABOVE = 5000  # remember at most this many finished users before forgetting old ones


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    """Result of asking to start a build."""

    allowed: bool
    busy: bool = False  # the user's previous build is still running
    wait_s: float = 0.0  # seconds until the next build is allowed (cooldown)


class MenuGuard:
    """Allows one build per user at a time and a pause of ``cooldown_s`` after each build.

    State lives in memory, so it resets when the bot restarts. That is fine for the purpose
    (a short-term brake), not for accounting.
    """

    def __init__(self, cooldown_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._busy: set[int] = set()
        self._finished_at: dict[int, float] = {}

    def acquire(self, user_id: int) -> GuardVerdict:
        """Try to start a build for the user; call ``release`` when it is over."""
        if user_id in self._busy:
            return GuardVerdict(False, busy=True)
        now = self._clock()
        finished = self._finished_at.get(user_id)
        if finished is not None and now - finished < self._cooldown_s:
            return GuardVerdict(False, wait_s=self._cooldown_s - (now - finished))
        self._busy.add(user_id)
        return GuardVerdict(True)

    def release(self, user_id: int) -> None:
        """Mark the build as finished (also after a failure) and start the cooldown."""
        self._busy.discard(user_id)
        now = self._clock()
        self._finished_at[user_id] = now
        if len(self._finished_at) > PRUNE_ABOVE:
            self._finished_at = {
                u: t for u, t in self._finished_at.items() if now - t < self._cooldown_s
            }
