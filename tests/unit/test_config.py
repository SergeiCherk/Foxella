"""Tests for application settings."""

import pytest

from nutrition_bot.config import Settings, get_settings


def test_defaults_match_approved_assumptions(settings: Settings) -> None:
    assert settings.norms.min_age == 18
    assert settings.norms.max_deficit == pytest.approx(0.20)
    assert settings.norms.gain_surplus == pytest.approx(0.10)
    assert settings.norms.min_kcal_female == 1200
    assert settings.norms.min_kcal_male == 1500
    assert settings.slip.spread_days == 3
    assert settings.slip.max_daily_correction == pytest.approx(0.10)
    assert settings.menu.meal_tolerance == pytest.approx(0.10)
    assert settings.preset.name == "base"


def test_activity_factors_cover_five_levels(settings: Settings) -> None:
    assert sorted(settings.norms.activity_factors.values()) == [1.2, 1.375, 1.55, 1.725, 1.9]


def test_secrets_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("LLM_API_KEY", "key")
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]
    assert loaded.bot_token.get_secret_value() == "123:abc"
    assert loaded.llm_api_key.get_secret_value() == "key"
    assert "123:abc" not in repr(loaded)  # secrets must not leak into logs


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_llm_and_menu_defaults(settings: Settings) -> None:
    assert settings.llm_model == "qwen3.8-flash"
    assert settings.llm_base_url == ""  # no default provider on purpose
    assert settings.llm_extra_body == {}
    assert settings.llm_max_tokens == 8000
    assert settings.llm_timeout_s == 90.0
    assert settings.menu.max_llm_retries == 2
    assert settings.menu.meal_tolerance == pytest.approx(0.10)
    assert sum(settings.menu.meal_shares.values()) == pytest.approx(1.0)
    assert settings.menu.quantity_steps == (0.5, 0.25)
    assert {"яйцо", "помидор", "банан"} <= set(settings.menu.whole_measures)
    assert settings.shopping.whole_measures == settings.menu.whole_measures
