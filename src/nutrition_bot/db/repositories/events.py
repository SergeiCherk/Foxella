"""Usage events for the beta statistics. Returns ``core`` types, stores no message text."""

import logging
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nutrition_bot.core.metrics import EventName, UsageEvent
from nutrition_bot.db.models import UserEventORM

logger = logging.getLogger(__name__)


class EventRepository:
    """Write and read usage events. The user must exist (events go with the user on delete)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, telegram_id: int, name: EventName) -> None:
        """Store that something happened now. Raises an ``IntegrityError`` for an unknown user."""
        self._session.add(UserEventORM(telegram_id=telegram_id, name=name.value))
        await self._session.commit()

    async def all_events(self) -> list[UsageEvent]:
        """Every stored event, oldest first, with timezone-aware times (UTC).

        A row with an event name this version does not know is skipped, so a newer database
        never breaks an older report.
        """
        rows = await self._session.execute(
            select(UserEventORM.telegram_id, UserEventORM.name, UserEventORM.created_at).order_by(
                UserEventORM.id
            )
        )
        events: list[UsageEvent] = []
        for telegram_id, name, created_at in rows.all():
            try:
                event_name = EventName(name)
            except ValueError:
                logger.warning("skipping an event with an unknown name")
                continue
            at = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
            events.append(UsageEvent(telegram_id, event_name, at))
        return events
