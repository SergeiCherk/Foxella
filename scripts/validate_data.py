"""Check foods.csv and measures.csv for typos and inconsistencies.

Usage: uv run python scripts/validate_data.py
"""

import sys

from nutrition_bot.db.seed import DataFileError, load_foods, load_measures, validate_data


def main() -> int:
    """Print problems found in the seed files; exit code 1 if there are any."""
    try:
        foods, measures = load_foods(), load_measures()
    except DataFileError as error:
        print(f"ERROR: {error}")
        return 1
    problems = validate_data(foods, measures)
    for problem in problems:
        print(f"- {problem}")
    print(f"{len(foods)} foods, {len(measures)} measures, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
