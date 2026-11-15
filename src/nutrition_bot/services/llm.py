"""Language model clients. The model only suggests dishes; code validates and computes.

``OpenAICompatibleLLM`` talks to any OpenAI-compatible chat API (Qwen3.8 Flash and others),
``FakeLLM`` is a scripted stand-in for tests and for running the bot without an API key. Both
implement ``core.menu.DishGenerator``.
"""

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

import openai

from nutrition_bot.config import Settings
from nutrition_bot.core.errors import LLMError, UnknownFoodError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import DishGenerator, DishRequest
from nutrition_bot.core.models import Dish, MealType

logger = logging.getLogger(__name__)

MEAL_LABELS = {
    MealType.BREAKFAST: "завтрак",
    MealType.LUNCH: "обед",
    MealType.DINNER: "ужин",
    MealType.SNACK: "перекус",
}

SYSTEM_PROMPT = """\
Ты помогаешь составлять простые домашние блюда из заданного списка продуктов.

Отвечай ТОЛЬКО одним JSON-объектом, без пояснений и без markdown. Формат:
{"dishes": [{"name": "Название блюда", "recipe": "Короткий рецепт.",
  "items": [{"food_id": 1, "measure_id": 2, "quantity": 1.5}]}]}

Правила:
1. Используй только food_id и measure_id из списка. measure_id должен относиться к тому же продукту.
2. quantity: число бытовых мер, например 0.5, 1 или 2.5. Штучные продукты (яйцо, помидор,
   банан, яблоко и подобные) считай только целыми числами: 1, 2, 3.
3. От 1 до 3 блюд на приём пищи. Блюда простые, названия разные и не из списка «не повторять».
4. recipe: 2-5 коротких предложений по-русски. Не указывай калории, белки, жиры и углеводы:
   их считает программа и сама подгоняет порции.
5. В items только продукты из списка. Соль, воду и специи можно упомянуть в рецепте.
6. Продукты уже приготовлены (варёные, запечённые) или не требуют готовки: не пиши, что их нужно
   варить заново.
"""


def build_prompt(request: DishRequest, catalog: Catalog) -> tuple[str, str]:
    """Build ``(system, user)`` prompts. Only data from our own catalog and validator is used."""
    lines: list[str] = []
    for food_id in sorted(set(request.allowed_food_ids)):
        try:
            food = catalog.get_food(food_id)
        except UnknownFoodError:
            continue
        measures = ", ".join(
            f"measure_id={m.id} «{m.name_ru}» (~{m.grams:g} г)"
            for m in catalog.measures_for(food_id)
        )
        lines.append(f"- food_id={food.id}: {food.name_ru}; меры: {measures}")

    parts = [
        f"Приём пищи: {MEAL_LABELS[request.meal_type]}.",
        f"Нужно примерно {request.target_kcal:.0f} ккал (программа всё равно пересчитает "
        "и подгонит порции).",
        "Доступные продукты:",
        *lines,
    ]
    if request.avoid_dish_names:
        parts.append("Не повторять блюда: " + "; ".join(request.avoid_dish_names))
    if request.feedback:
        parts.append("В прошлом ответе были ошибки, исправь их:")
        parts += [f"- {problem}" for problem in request.feedback]
    return SYSTEM_PROMPT, "\n".join(parts)


def dishes_to_json(dishes: Sequence[Dish]) -> str:
    """Serialise dishes in the exact format the model is asked to produce (used by tests)."""
    return json.dumps(
        {
            "dishes": [
                {
                    "name": d.name,
                    "recipe": d.recipe_text,
                    "items": [
                        {"food_id": i.food_id, "measure_id": i.measure_id, "quantity": i.quantity}
                        for i in d.items
                    ],
                }
                for d in dishes
            ]
        },
        ensure_ascii=False,
    )


class FakeLLM:
    """Scripted stand-in: returns the given answers in order; an ``Exception`` item is raised."""

    def __init__(self, responses: Sequence[str | Exception] = ()) -> None:
        self._responses = list(responses)
        self.requests: list[DishRequest] = []

    async def generate(self, request: DishRequest) -> str:
        """Record the request and return (or raise) the next scripted answer."""
        self.requests.append(request)
        if not self._responses:
            raise LLMError("FakeLLM has no more scripted answers")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OpenAICompatibleLLM:
    """Client for any OpenAI-compatible chat API (Qwen on Alibaba, Novita, Venice, OpenRouter...).

    Only ``model``, ``messages`` and ``max_tokens`` are always sent; provider-specific options
    (for example ``{"enable_thinking": false}``) come from ``extra_body`` in the settings.
    """

    def __init__(
        self,
        catalog: Catalog,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 8000,
        timeout_s: float = 90.0,
        extra_body: dict[str, Any] | None = None,
        client: Any = None,
    ) -> None:
        self._catalog = catalog
        self._model = model
        self._max_tokens = max_tokens
        self._extra_body = extra_body or None
        self._client: Any = client or openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_s
        )

    async def generate(self, request: DishRequest) -> str:
        """Ask the model for dishes and return the text of its answer.

        Reasoning that a provider inlines as ``<think>`` blocks is removed. Raises ``LLMError``
        on API errors, truncation (``finish_reason == "length"``) or an empty answer.
        """
        system, user = build_prompt(request, self._catalog)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as error:
            raise LLMError(f"LLM request failed: {type(error).__name__}") from error
        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise LLMError("the model returned no choices")
        if choice.finish_reason == "length":
            raise LLMError("the answer was cut off at max_tokens")
        text = THINK_BLOCK.sub("", choice.message.content or "").strip()
        if not text:
            raise LLMError("the model returned no text")
        logger.info("LLM answered with %d characters", len(text))
        return text


def build_llm(settings: Settings, catalog: Catalog) -> DishGenerator:
    """The real client if the settings are complete, otherwise the key-less ``FakeLLM``.

    ``FakeLLM`` with no scripted answers always fails, so every meal falls back to our own
    dishes: the bot stays fully usable without any LLM account.
    """
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key or not settings.llm_base_url:
        logger.warning("LLM_API_KEY or LLM_BASE_URL is not set: using built-in dishes only")
        return FakeLLM()
    return OpenAICompatibleLLM(
        catalog,
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
        extra_body=settings.llm_extra_body,
    )
