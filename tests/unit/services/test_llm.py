"""Tests for services.llm: prompt, scripted fake, OpenAI-compatible client (stubbed)."""

from types import SimpleNamespace
from typing import Any

import openai
import pytest

from nutrition_bot.config import MenuConfig, Settings
from nutrition_bot.core.errors import LLMError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import DishRequest, MealSource, build_meal, parse_dishes
from nutrition_bot.core.models import Dish, DishItem, MealType, Nutrients
from nutrition_bot.services.llm import (
    SYSTEM_PROMPT,
    FakeLLM,
    OpenAICompatibleLLM,
    build_llm,
    build_prompt,
    dishes_to_json,
)
from tests.catalog_helpers import cooked_or_ready_ids, real_catalog

CFG = MenuConfig()


@pytest.fixture(scope="module")
def real() -> tuple[Catalog, dict[str, int]]:
    return real_catalog()


def request_for(ids: tuple[int, ...], **kw: Any) -> DishRequest:
    return DishRequest(MealType.LUNCH, 612.4, ids, **kw)


# ----------------------------------------------------------------- prompt


def test_prompt_lists_only_allowed_foods_with_their_measures(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    chicken, oil = ids["chicken_breast_cooked"], ids["sunflower_oil"]
    system, user = build_prompt(request_for((chicken, oil)), catalog)

    assert f"\n{chicken} Куриная грудка (готовая): " in user
    assert f"\n{oil} Масло подсолнечное: " in user
    breast = next(m for m in catalog.measures_for(chicken) if m.name_ru == "грудка")
    assert f"{breast.id} грудка ~150г" in user
    assert "Рис" not in user  # foods that are not allowed never reach the model
    assert "обед" in user
    assert "612 ккал" in user
    assert system == SYSTEM_PROMPT


def test_prompt_contains_avoid_list_and_feedback_only_when_given(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    plain = build_prompt(request_for((ids["apple"],)), catalog)[1]
    assert "Не повторять" not in plain
    assert "ошибки" not in plain

    full = build_prompt(
        request_for(
            (ids["apple"],),
            avoid_dish_names=("Яблоко с миндалём", "Кефир с бананом"),
            feedback=("dish 1: unknown food_id 999",),
        ),
        catalog,
    )[1]
    assert "Не повторять блюда: Яблоко с миндалём; Кефир с бананом" in full
    assert "- dish 1: unknown food_id 999" in full


def test_prompt_skips_unknown_ids_and_duplicates(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    user = build_prompt(request_for((ids["apple"], ids["apple"], 999_999)), catalog)[1]
    assert user.count(f"\n{ids['apple']} Яблоко: ") == 1  # duplicate and unknown id skipped
    assert "999999" not in user
    assert user.count("Яблоко") == 1


def test_system_prompt_states_the_rules_that_the_validator_enforces() -> None:
    for fragment in (
        "ТОЛЬКО одним JSON",
        "food_id",
        "measure_id",
        "quantity",
        "Не указывай калории",
    ):
        assert fragment in SYSTEM_PROMPT


# ----------------------------------------------------------------- serialisation


def test_dishes_to_json_round_trips_through_the_parser(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    chicken = ids["chicken_breast_cooked"]
    measure = catalog.measures_for(chicken)[0]
    dish = Dish("Курица", (DishItem(chicken, measure.id, 1.5),), "Запеките курицу.")
    parsed = parse_dishes(dishes_to_json([dish]), catalog, cooked_or_ready_ids(catalog), CFG)
    assert parsed == [dish]


# ----------------------------------------------------------------- FakeLLM


async def test_fake_llm_returns_scripted_answers_in_order_and_records_requests() -> None:
    fake = FakeLLM(["first", "second"])
    req = request_for((1,))
    assert await fake.generate(req) == "first"
    assert await fake.generate(req) == "second"
    assert fake.requests == [req, req]


async def test_fake_llm_raises_scripted_errors_and_runs_dry() -> None:
    fake = FakeLLM([LLMError("boom"), "ok"])
    with pytest.raises(LLMError, match="boom"):
        await fake.generate(request_for((1,)))
    assert await fake.generate(request_for((1,))) == "ok"
    with pytest.raises(LLMError, match="no more"):
        await fake.generate(request_for((1,)))


# ------------------------------------------------------ OpenAI-compatible


class StubCompletions:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result, error, []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def stub_client(**kw: Any) -> Any:
    return SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions(**kw)))


def reply(content: Any, finish_reason: str = "stop", **message: Any) -> Any:
    msg = SimpleNamespace(content=content, **message)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=msg)])


def make(client: Any, **kw: Any) -> OpenAICompatibleLLM:
    catalog = kw.pop("catalog")
    return OpenAICompatibleLLM(
        catalog, "key", "https://llm.example/v1", "qwen3.8-flash", client=client, **kw
    )


async def test_the_client_sends_system_and_user_messages_and_returns_the_text(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    client = stub_client(result=reply('{"dishes": []}'))
    llm = make(client, catalog=catalog, max_tokens=1234)

    assert await llm.generate(request_for((ids["apple"],))) == '{"dishes": []}'

    (call,) = client.chat.completions.calls
    assert call["model"] == "qwen3.8-flash"
    assert call["max_tokens"] == 1234
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["messages"][0]["content"] == SYSTEM_PROMPT
    assert "Яблоко" in call["messages"][1]["content"]
    assert set(call) == {"model", "max_tokens", "messages"}  # nothing provider-specific by default


async def test_provider_options_are_sent_as_extra_body(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    client = stub_client(result=reply("{}"))
    llm = make(client, catalog=catalog, extra_body={"enable_thinking": False})
    await llm.generate(request_for((ids["apple"],)))
    assert client.chat.completions.calls[0]["extra_body"] == {"enable_thinking": False}


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('<think>hmm {not json}</think>{"dishes": []}', '{"dishes": []}'),
        ('<THINK>\nmulti\nline\n</THINK>\n\n{"a": 1}', '{"a": 1}'),
        ("<think>a</think><think>b</think>{}", "{}"),
        ("  {}  ", "{}"),
    ],
)
async def test_inline_reasoning_is_removed(
    real: tuple[Catalog, dict[str, int]], content: str, expected: str
) -> None:
    catalog, ids = real
    llm = make(stub_client(result=reply(content)), catalog=catalog)
    assert await llm.generate(request_for((ids["apple"],))) == expected


async def test_separate_reasoning_content_is_ignored(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    llm = make(
        stub_client(result=reply("{}", reasoning_content="secret thoughts")), catalog=catalog
    )
    assert await llm.generate(request_for((ids["apple"],))) == "{}"


async def test_api_errors_become_llm_errors_without_leaking_secrets(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    # The SDK only stores the request object, so a stand-in is enough (no HTTP library needed).
    boom = openai.APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]
    llm = OpenAICompatibleLLM(
        catalog, "sk-secret-key", "https://llm.example/v1", "m", client=stub_client(error=boom)
    )
    with pytest.raises(LLMError) as exc:
        await llm.generate(request_for((ids["apple"],)))
    assert "APIConnectionError" in str(exc.value)
    assert "sk-secret-key" not in str(exc.value)
    assert exc.value.__cause__ is boom


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (reply("{}", finish_reason="length"), "cut off"),
        (reply(None), "no text"),
        (reply("   "), "no text"),
        (reply("<think>only thoughts</think>"), "no text"),
        (SimpleNamespace(choices=[]), "no choices"),
    ],
)
async def test_unusable_answers_raise_llm_error(
    real: tuple[Catalog, dict[str, int]], response: Any, message: str
) -> None:
    catalog, ids = real
    llm = make(stub_client(result=response), catalog=catalog)
    with pytest.raises(LLMError, match=message):
        await llm.generate(request_for((ids["apple"],)))


def test_a_real_sdk_client_is_created_without_network_access() -> None:
    llm = OpenAICompatibleLLM(
        Catalog([], []), "test-key", "https://llm.example/v1", "m", timeout_s=5.0
    )
    assert isinstance(llm._client, openai.AsyncOpenAI)


async def test_the_client_works_as_a_dish_generator_end_to_end(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    chicken, rice = ids["chicken_breast_cooked"], ids["rice_white_cooked"]
    breast = next(m for m in catalog.measures_for(chicken) if m.name_ru == "грудка")
    ladle = next(m for m in catalog.measures_for(rice) if m.name_ru == "половник")
    dish = Dish(
        "Курица с рисом",
        (DishItem(chicken, breast.id, 1), DishItem(rice, ladle.id, 2)),
        "Запеките курицу и отварите рис.",
    )
    raw = "<think>считаю порции</think>" + dishes_to_json([dish])
    llm = make(stub_client(result=reply(raw)), catalog=catalog)

    result = await build_meal(
        llm, catalog, MealType.LUNCH, Nutrients(520, 0, 0, 0), cooked_or_ready_ids(catalog), CFG
    )
    assert result.source is MealSource.LLM
    assert result.meal.dishes[0].name == "Курица с рисом"
    assert result.nutrients.kcal == pytest.approx(507.5)


# ----------------------------------------------------------------- build_llm


def settings_with(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "kw",
    [{}, {"llm_api_key": "k"}, {"llm_base_url": "https://llm.example/v1"}],
    ids=["nothing", "key_only", "url_only"],
)
def test_incomplete_settings_give_the_keyless_fake(kw: dict[str, str]) -> None:
    assert isinstance(build_llm(settings_with(**kw), Catalog([], [])), FakeLLM)


def test_complete_settings_give_the_real_client() -> None:
    settings = settings_with(
        llm_api_key="k",
        llm_base_url="https://llm.example/v1",
        llm_model="qwen/qwen3.8-flash",
        llm_extra_body={"enable_thinking": False},
        llm_max_tokens=500,
    )
    llm = build_llm(settings, Catalog([], []))
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm._model == "qwen/qwen3.8-flash"
    assert llm._max_tokens == 500
    assert llm._extra_body == {"enable_thinking": False}


def test_llm_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.novita.ai/openai")
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3.8-flash")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"enable_thinking": false}')
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]
    assert loaded.llm_extra_body == {"enable_thinking": False}
    assert loaded.llm_model == "qwen/qwen3.8-flash"
    assert "secret" not in repr(loaded)
    assert isinstance(build_llm(loaded, Catalog([], [])), OpenAICompatibleLLM)


# ---- unknown eaten food


def test_the_eaten_prompt_lists_the_phrases_foods_and_feedback(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    from nutrition_bot.core.eaten import EatenRequest
    from nutrition_bot.services.llm import EATEN_PROMPT, build_eaten_prompt

    catalog, ids = real
    request = EatenRequest(("лагман",), (ids["pasta_cooked"],), ("food 1: wrong",))
    system, user = build_eaten_prompt(request, catalog)
    assert system == EATEN_PROMPT
    assert '"foods"' in system
    assert "- лагман" in user
    assert f"{ids['pasta_cooked']} Макароны (варёные):" in user
    assert "- food 1: wrong" in user


async def test_the_client_decomposes_with_the_eaten_prompt(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    from nutrition_bot.core.eaten import EatenRequest
    from nutrition_bot.services.llm import EATEN_PROMPT

    catalog, ids = real
    client = stub_client(result=reply('{"foods": []}'))
    llm = make(client, catalog=catalog)
    assert llm.available
    text = await llm.decompose(EatenRequest(("лагман",), (ids["pasta_cooked"],)))
    assert text == '{"foods": []}'
    assert client.chat.completions.calls[0]["messages"][0]["content"] == EATEN_PROMPT


def test_a_fake_without_answers_is_not_available() -> None:
    assert not FakeLLM().available
    assert FakeLLM(eaten=["{}"]).available
