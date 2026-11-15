"""Print the beta usage report: how many people did what and how many came back.

Only counts of people are printed, never ids or texts.
Usage: uv run python scripts/beta_report.py
"""

import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from nutrition_bot.config import get_settings
from nutrition_bot.core.metrics import BetaSummary, summarize
from nutrition_bot.db.repositories.events import EventRepository
from nutrition_bot.db.session import create_engine, create_session_factory


def render_report(summary: BetaSummary) -> str:
    """The report as plain text."""
    lines = [f"People with at least one event: {summary.users}"]
    lines += [f"  {name.value}: {count}" for name, count in summary.by_event.items()]
    lines.append("Came back (any event) in a week, among people whose week is over:")
    for item in summary.returns:
        if item.eligible == 0:
            lines.append(f"  week {item.week}: nobody has reached it yet")
        else:
            share = round(100 * item.returned / item.eligible)
            lines.append(f"  week {item.week}: {item.returned} of {item.eligible} ({share} %)")
    return "\n".join(lines)


async def main() -> int:
    """Read the events from the configured database and print the report."""
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            events = await EventRepository(session).all_events()
    except SQLAlchemyError:
        print("ERROR: cannot read events. Did you run `alembic upgrade head`?")
        return 1
    finally:
        await engine.dispose()
    print(render_report(summarize(events, datetime.now(UTC))))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
