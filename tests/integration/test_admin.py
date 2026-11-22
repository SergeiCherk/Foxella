"""/admin: statistics for the owner only."""

from nutrition_bot import texts
from nutrition_bot.config import Settings
from nutrition_bot.services.llm import FakeLLM
from tests.integration.conftest import AppFactory

ADMIN = 777


def admin_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"admin_ids": frozenset({ADMIN})})


async def test_strangers_do_not_see_the_admin_command(
    make_app: AppFactory, settings: Settings
) -> None:
    app = await make_app(use=admin_settings(settings))
    replies = await app.say("/admin", user_id=1)
    assert [r.text for r in replies] == [texts.FALLBACK]
    assert not any("Статистика" in r.text for r in await app.press("admin:refresh", user_id=1))


async def test_nobody_is_admin_by_default(make_app: AppFactory) -> None:
    app = await make_app()
    assert [r.text for r in await app.say("/admin", user_id=ADMIN)] == [texts.FALLBACK]


async def test_admin_sees_counts_of_people_and_actions(
    make_app: AppFactory, settings: Settings
) -> None:
    app = await make_app(use=admin_settings(settings))
    await app.onboard(user_id=1)
    await app.onboard(user_id=2, goal="gain")
    await app.say("/shopping", user_id=1)  # no menu yet: not counted

    (reply,) = await app.say("/admin", user_id=ADMIN)
    assert "Всего: <b>2</b>" in reply.text
    assert "Новых: 2 · 2 · 2" in reply.text
    assert "Прошли знакомство: 2 (людей: 2)" in reply.text
    assert "Списки покупок: 0 (людей: 0)" in reply.text
    assert "Похудеть 2 · держать форму 0 · набрать 0" not in reply.text
    assert "набрать 1" in reply.text
    assert "Женщин 2 · мужчин 0" in reply.text
    assert texts.ADMIN_LLM_OFF in reply.text
    assert reply.buttons == ("admin:refresh",)
    for user_id in (1, 2):  # no ids in the report
        assert f" {user_id}:" not in reply.text

    (fresh,) = await app.press("admin:refresh", user_id=ADMIN)
    assert "Всего: <b>2</b>" in fresh.text


async def test_admin_sees_the_connected_model(make_app: AppFactory, settings: Settings) -> None:
    app = await make_app(llm=FakeLLM(["{}"]), use=admin_settings(settings))
    (reply,) = await app.say("/admin", user_id=ADMIN)
    assert f"<code>{settings.llm_model}</code>" in reply.text


def test_admin_ids_are_read_from_a_comma_separated_list() -> None:
    parsed = Settings(_env_file=None, admin_ids="123, 456,")  # type: ignore[call-arg]
    assert parsed.admin_ids == frozenset({123, 456})
    assert Settings(_env_file=None, admin_ids="").admin_ids == frozenset()  # type: ignore[call-arg]
