# Contributing

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync`.
2. Install hooks: `uv run pre-commit install`.
3. Before a pull request run:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/
   uv run pytest --cov
   ```
4. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
5. Rules of the project: calories and macros are computed by code, never by an LLM;
   `core/` must not import aiogram or the database; never commit secrets.

## Документация и примеры

- Документация проверяется тестами (`tests/unit/test_docs.py`): ссылки между файлами, имена настроек, команды бота, переменные окружения и значения по умолчанию в README должны совпадать с кодом. Если тест падает, поправьте документ или код, а не тест.
- Примеры диалогов в `examples/` создаются скриптом из настоящих обработчиков. После изменения текстов, данных или норм обновите их:

  ```bash
  uv run python -m tests.render_examples
  ```
- Новое допущение (порог, лимит) заносите в `config.py` с пометкой `ASSUMPTION` и добавьте строку в таблицу в `docs/decisions.md`.
- Данные продуктов меняйте в `src/nutrition_bot/data/*.csv` и проверяйте `uv run python scripts/validate_data.py`. Источники и лицензии: `docs/data-sources.md`.
