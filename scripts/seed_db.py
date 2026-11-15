"""Fill the database with foods and measures. Run after `alembic upgrade head`.

Usage: uv run python scripts/seed_db.py
"""

import asyncio
import sys

from nutrition_bot.config import get_settings
from nutrition_bot.db.repositories.foods import FoodRepository
from nutrition_bot.db.seed import DataFileError, load_foods, load_measures, validate_data
from nutrition_bot.db.session import create_engine, create_session_factory


async def main() -> int:
    """Validate the seed files, then upsert them into the configured database."""
    try:
        foods, measures = load_foods(), load_measures()
    except DataFileError as error:
        print(f"ERROR: {error}")
        return 1
    problems = validate_data(foods, measures)
    if problems:
        print("Refusing to seed, the data has problems:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    engine = create_engine(get_settings().database_url)
    async with create_session_factory(engine)() as session:
        await FoodRepository(session).seed(foods, measures)
    await engine.dispose()
    print(f"Seeded {len(foods)} foods and {len(measures)} measures")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
