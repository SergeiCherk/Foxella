# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Portions sound more natural: a quarter ("1¼") is used only for glasses and spoons; a bunch, a
  pack or a ladle go in whole and half numbers. If a meal cannot be fitted that way, quarters for
  any measure are still used as a last resort, so menus are not lost (`MenuConfig.fine_measures`).
- The target-weight check reads like a conversation: the button asks "За какой срок я дойду до
  цели?" and the answers say plainly whether the pace is safe (the calculation is unchanged).
- `/start` greets with the Foxella picture (`src/nutrition_bot/assets/welcome.jpg`); if the picture
  cannot be sent, the greeting is plain text.
- A permanent button panel under the input field (menu, shopping list, "not by plan", profile) is
  set after onboarding and by `/start` for known people, and removed by `/delete_me`. Free-text steps
  no longer treat the panel labels as answers.
- The menu is easier to read: a short header card for each day, one message per meal with bold
  titles, an emoji for each food group, bold household measures and the recipe in a folded
  "How to cook" block. Messages are sent as Telegram HTML; dish names and recipes are escaped
  and long recipes are cut at a word boundary (`handlers/render.py`).
- The greeting now introduces the bot as Foxella.

### Added
- The disclaimer is confirmed with a "Понятно, мне есть 18" button before the first question;
  the time is stored in `users.disclaimer_accepted_at` (migration `0004`). People saved earlier
  stay with an empty value and are asked once on their next `/start`; editing the profile keeps
  the first confirmation.
- The greeting picture is uploaded once per run and then sent by its Telegram `file_id`
  (kept in memory; a refused id is forgotten and the file is uploaded again).
- CI checks the SHA256 of the downloaded gitleaks archive before unpacking it.
- Usage events for the beta (stage 8): "onboarding done", "menu received" and "slip started" are
  stored in the new `user_events` table (migration `0003`) as a fixed name and a time, with no
  message text. They are removed with the user by `/delete_me`; a failed write never breaks a
  conversation. `scripts/beta_report.py` prints how many people did what and how many came back
  in week 2 and week 3 (pure logic in `core/metrics.py`).

### Changed
- Whole-piece foods (eggs, tomatoes, cucumbers, apples, bananas and the like) are now always
  whole numbers: menu portions use step 1 instead of 0.5/0.25 and the shopping list rounds up
  to whole pieces. The list is `MenuConfig.whole_measures` / `ShoppingConfig.whole_measures`.
  When whole pieces cannot flex, the other ingredients are re-scaled to fill the kcal target.
  The LLM prompt now asks for whole numbers for such foods; example dialogs were regenerated.

### Added
- Documentation: full README, `docs/architecture.md`, `docs/decisions.md`, `docs/data-sources.md`,
  example dialogs in `examples/` generated from the real handlers (`tests/render_examples.py`).
- Tests that keep the documentation in sync with the code (`tests/unit/test_docs.py`).

### Fixed
- Menu without an LLM now uses what the person has: staples (oil, sugar, honey, butter) count as
  available, built-in dishes accept interchangeable variants (any cottage cheese, oil, bread, rice),
  and the omelette no longer needs a raw egg, which a menu can never contain. 26 built-in dishes
  instead of 14; a 3-day menu without an LLM has no repeated dish. In the shopping list staples are
  shown in a separate block "check what you have at home".
- The HTTP session and the database connection are now closed when Telegram is unreachable at start.

### Added
- Optional target-weight check ("check my term" button after onboarding and in the profile): a goal
  that is faster than a safe plan is refused with a realistic term. Nothing is stored.
- Doctor note when the computed norm is below the absolute minimum (1200 kcal for women, 1500 for
  men), shown after onboarding and in the profile; the numbers themselves are never raised.
- Anti-spam guard for menu building: one build per user at a time and a 30 s pause afterwards.
- Time limit for building a menu (120 s): a stalled LLM call is cancelled and the remaining meals
  come from the built-in dishes. The bot shows "typing..." while it builds.
- Old or unexpected inline buttons are answered with a short hint instead of an endless spinner.
- Telegram layer (Stage 5): onboarding with the adult-only check, `/profile`, `/delete_me`,
  `/menu` (1-3 days, free-text product list with clarifying buttons), `/shopping`, `/slip`
  (gentle correction spread over the next days and applied to the next menu).
- Free-text product parser (`services/food_parser.py`): word forms, quantities, typos, ambiguity.
- User tables (`users`, `user_foods`, `user_menus`) with Alembic migration 0002; the user row
  holds only the Telegram id and the profile, and deleting it removes everything.
- `core.menu.build_menu`, `core.menu.menu_food_ids`, `core.slip.apply_adjustment`.
- The bot applies migrations, seeds the food data and sets the command menu at startup.
- "What is missing" hints (`core/balance.py`): per-meal protein, daily protein, vegetables and fruit
  (WHO: at least 400 g, potatoes not counted) and fibre (WHO: at least 25 g, scaled down for
  plans below 2000 kcal); the same check for the plain list of products the user has.
- Shopping list (`core/shopping.py`): sums the menus of several days, converts cooked food to the
  raw food to buy, skips products the user already has, shows amounts in household measures
  rounded up, grouped by category.
- `BalanceConfig` and `ShoppingConfig` in `config.py`; hint texts, meal names and shopping section
  titles in `texts.py`.
- Menu assembly (`core/menu.py`): validation of model output, portion fitting to the per-meal kcal
  target (+-10 %), feedback retries (at most 3 calls), 14 own fallback dishes, whole-day builder
  without repeated dishes.
- LLM clients (`services/llm.py`): `OpenAICompatibleLLM` for any OpenAI-compatible API (target model:
  Qwen3.8 Flash; base URL, model id and provider options come from `.env`), a scripted `FakeLLM`,
  and `build_llm`, which falls back to built-in dishes when no key is configured.
- `scripts/try_llm.py`: one real request to the configured model, with a validation report.
- Gentle recalculation after eating off-plan (`core/slip.py`): spread over up to 3 days, at most 10 %
  of the norm per day, never below the kcal floor, small deviations ignored; calm slip messages
  in `texts.py` guarded by a tone test.
- Nutrients of dishes, meals and days (`core/nutrition.py`) and conversion of cooked weight to raw
  weight for shopping lists; `Dish`, `DishItem`, `Meal`, `MealType` domain types.
- Weight-goal pace check (`check_weight_goal`): refuses unrealistic targets and suggests safe duration.
- Food catalog: schema and migration `0001` (foods, aliases, measures), 116 foods and 152 household
  measures in CSV, validation of the data files, idempotent seeding, `Catalog` and
  `measures` (measure -> grams -> nutrients) in `core`.
- Daily calorie and macro norms (`core/norms.py`): Mifflin-St Jeor, goals, kcal floor, validation.
- Project skeleton: src-layout, settings, logging, bot assembly, Alembic, tests, CI, Docker.

### Fixed
- Alembic's logging setup no longer disables the application loggers.
- Debug logging no longer prints SQL parameters (profile data) from `aiosqlite`/SQLAlchemy.
