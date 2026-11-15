"""The documentation must not drift away from the code it describes."""

import re
from pathlib import Path

import pytest

from nutrition_bot import config as config_module
from nutrition_bot.config import Settings
from nutrition_bot.texts import BOT_COMMANDS

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]
MARKDOWN = [*DOCS, *sorted((ROOT / "examples").glob("*.md"))]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: p.name)
def test_relative_links_point_to_existing_files(path: Path) -> None:
    for target in re.findall(r"\]\(([^)\s]+)\)", text(path)):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        file_part = target.split("#", 1)[0]
        assert (path.parent / file_part).exists(), f"{path.name}: broken link {target}"


def test_config_fields_named_in_the_docs_exist() -> None:
    """`ClassName.field` and `Class` mentions in decisions.md must match config.py."""
    body = text(ROOT / "docs" / "decisions.md")
    for cls_name, field in re.findall(r"`([A-Z][A-Za-z]+Config)\.([a-z_]+)`", body):
        model = getattr(config_module, cls_name)
        assert field in model.model_fields, f"{cls_name}.{field} is not in config.py"
    for cls_name in set(re.findall(r"`([A-Z][A-Za-z]+Config)`", body)):
        assert hasattr(config_module, cls_name), cls_name


def test_environment_variables_in_the_readme_match_the_settings() -> None:
    readme = text(ROOT / "README.md")
    table = readme.split("## Настройка", 1)[1].split("## Примеры", 1)[0]
    documented = set(re.findall(r"^\| `([A-Z_]+)` \|", table, flags=re.MULTILINE))
    simple = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.annotation in (str, int, float, dict[str, object])
        or name.startswith(("bot_", "llm_"))
    }
    expected = {
        n for n in simple if n.startswith(("BOT_", "LLM_")) or n in {"DATABASE_URL", "LOG_LEVEL"}
    }
    assert documented == expected


def test_every_bot_command_is_described_in_the_readme() -> None:
    readme = text(ROOT / "README.md")
    for command in BOT_COMMANDS:
        assert f"`/{command}`" in readme, command


def test_defaults_in_the_readme_table_are_the_real_ones() -> None:
    readme = text(ROOT / "README.md")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert f"`{settings.llm_model}`" in readme
    assert f"`{settings.llm_max_tokens}`" in readme
    assert f"| `LLM_TIMEOUT_S` | `{settings.llm_timeout_s:g}` |" in readme
    assert settings.database_url in readme
    assert settings.log_level in readme


def test_commands_in_the_readme_use_files_that_exist() -> None:
    readme = text(ROOT / "README.md")
    for script in re.findall(r"uv run python (scripts/\w+\.py)", readme):
        assert (ROOT / script).exists(), script
    for module in re.findall(r"uv run python -m ([\w.]+)", readme):
        if module != "nutrition_bot":
            assert (ROOT / (module.replace(".", "/") + ".py")).exists(), module
    for test_path in re.findall(r"uv run pytest (tests/\S+\.py)", readme):
        assert (ROOT / test_path).exists(), test_path


def test_the_example_files_listed_in_the_index_exist() -> None:
    index = text(ROOT / "examples" / "README.md")
    names = re.findall(r"\[(\d\d-[\w-]+\.md)\]", index)
    assert len(names) >= 4
    on_disk = {p.name for p in (ROOT / "examples").glob("[0-9]*.md")}
    assert set(names) == on_disk


def test_the_dependency_rule_in_the_docs_names_a_real_test() -> None:
    architecture = text(ROOT / "docs" / "architecture.md")
    assert "tests/unit/core/test_architecture.py" in architecture
    assert (ROOT / "tests/unit/core/test_architecture.py").exists()


def test_the_number_of_built_in_dishes_in_the_docs_is_the_real_one() -> None:
    from nutrition_bot.core.menu import FALLBACK_TEMPLATES

    for name in ("data-sources.md", "decisions.md"):
        numbers = {int(n) for n in re.findall(r"(\d+) встроенных блюд", text(ROOT / "docs" / name))}
        assert numbers, name
        assert numbers == {len(FALLBACK_TEMPLATES)}, (name, numbers)


def test_the_staples_row_in_the_decisions_table_matches_the_config() -> None:
    from nutrition_bot.config import MenuConfig

    body = text(ROOT / "docs" / "decisions.md")
    assert "`MenuConfig.staple_codes`" in body
    assert set(MenuConfig().staple_codes) == {
        "sunflower_oil",
        "olive_oil",
        "butter",
        "sugar",
        "honey",
    }
