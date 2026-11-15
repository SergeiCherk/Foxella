"""Smoke tests for the command-line scripts."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def run(script: str, database_url: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url} if database_url else None
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )


def test_validate_data_script_passes_on_real_data() -> None:
    result = run("validate_data.py")
    assert result.returncode == 0
    assert "0 problem(s)" in result.stdout


def test_seed_script_fills_a_migrated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'seed.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")

    result = run("seed_db.py", database_url=url)
    assert result.returncode == 0, result.stderr
    assert "Seeded 116 foods" in result.stdout


def test_try_llm_script_explains_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}
    env["LLM_API_KEY"] = ""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "try_llm.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert "not both set" in result.stdout


def migrated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    db_file = tmp_path / "beta.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    return url, db_file


def test_beta_report_on_an_empty_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url, _ = migrated_database(tmp_path, monkeypatch)
    result = run("beta_report.py", database_url=url)
    assert result.returncode == 0, result.stderr
    assert "People with at least one event: 0" in result.stdout
    assert "week 2: nobody has reached it yet" in result.stdout


def test_beta_report_counts_people_and_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, db_file = migrated_database(tmp_path, monkeypatch)
    with sqlite3.connect(db_file) as conn:
        for user_id in (1, 2):
            conn.execute(
                "INSERT INTO users (telegram_id, sex, age, height_cm, weight_kg, activity, goal,"
                " pending_adjust, created_at) VALUES (?, 'male', 30, 180, 80, 'light',"
                " 'maintain', '[]', '2020-01-01 00:00:00')",
                (user_id,),
            )
        events = [
            (1, "onboarding_done", "2020-01-01 10:00:00"),
            (1, "menu_received", "2020-01-09 10:00:00"),  # day 8: back in week 2
            (2, "onboarding_done", "2020-01-01 11:00:00"),
            (2, "slip_pressed", "2020-01-02 11:00:00"),  # only week 1
        ]
        conn.executemany(
            "INSERT INTO user_events (telegram_id, name, created_at) VALUES (?, ?, ?)", events
        )
    result = run("beta_report.py", database_url=url)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "People with at least one event: 2" in out
    assert "onboarding_done: 2" in out
    assert "menu_received: 1" in out
    assert "slip_pressed: 1" in out
    assert "week 2: 1 of 2 (50 %)" in out
    assert "week 3: 0 of 2 (0 %)" in out


def test_beta_report_explains_a_database_without_migrations(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'empty.db').as_posix()}"
    result = run("beta_report.py", database_url=url)
    assert result.returncode == 1
    assert "alembic upgrade head" in result.stdout
