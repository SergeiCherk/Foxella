"""Guard for iron rule 5: core/ knows nothing about Telegram, the database or the network."""

import ast
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parents[3] / "src" / "nutrition_bot" / "core"
FORBIDDEN = {
    "aiogram",
    "sqlalchemy",
    "alembic",
    "aiosqlite",
    "anthropic",
    "openai",
    "httpx",
    "requests",
}
FORBIDDEN_INTERNAL = {"nutrition_bot.db", "nutrition_bot.handlers", "nutrition_bot.services"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


CORE_FILES = sorted(CORE_DIR.glob("*.py"))


def test_core_files_are_discovered() -> None:
    assert CORE_FILES, "core/ must contain python files"


@pytest.mark.parametrize("path", CORE_FILES, ids=lambda p: p.name)
def test_core_has_no_forbidden_imports(path: Path) -> None:
    for module in _imports(path):
        assert module.split(".")[0] not in FORBIDDEN, f"{path.name} imports {module}"
        assert not any(module.startswith(p) for p in FORBIDDEN_INTERNAL), (
            f"{path.name} imports {module}"
        )
