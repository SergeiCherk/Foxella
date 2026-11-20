# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Docker: uv 0.12 (the version that wrote uv.lock), only the image's own Python, scripts in
  the image, logs capped at 3 x 10 MB. Server guide `docs/deploy.md`, backups
  `scripts/backup_db.sh`.
- Conversations in progress are kept in the database (`db/fsm_storage.py`, table
  `fsm_states`, migration `0007`) instead of memory: after a restart people go on from the
  same step. A finished conversation is deleted at once, an unfinished one after 24 hours.
- A menu day is first asked for in one call (`MenuConfig.day_requests`); each meal is checked
  on its own and only failing meals are asked again one by one, with their problems. A day
  took 2 calls and 18 s on Qwen3.8 Flash instead of 4+.

### Added
- Answers to "which one?" ("курица" -> breast) are remembered per person (migration
  `0006`) and used next time with a short note.
- "салат из огурцов и помидоров" is cucumbers and tomatoes, not lettuce.

### Fixed
- A second slip on the same day replaced the first; corrections now add up and the 10 %
  daily cap applies to the sum.
- "Instead of a meal" was counted as extra: the confirmation now asks "on top of the plan"
  or "instead of breakfast/lunch/snack/dinner" and takes that meal's planned kcal off.
- A slip was always compared with the first day of the menu; now with the menu day that
  falls on today (by the menu's date).

### Added
- Unknown food in "I ate" ("лагман") is split by the model into our foods
  (`core/eaten.py`, `LanguageModel.decompose`); code validates it like menu dishes, computes the
  calories and shows it as an estimate to confirm. At most 3 phrases a message and one call per
  user every 10 s (`SlipConfig.llm_*`); without a model nothing changes.
- 70 ready dishes and drinks for "I ate" (category `dish`): fast food, drinks and desserts
  from USDA, home dishes (borscht, pelmeni, plov, olivier, ...) computed from our foods by
  `dish_recipes.csv` (source `recipe`). They never reach menus or the model's list.
- The parser reads "X с Y" as two foods unless the phrase is one alias, drops joiners from
  aliases too ("овсянка на молоке" was never found) and reads number words in any case
  ("из двух яиц").
- Food restrictions in the profile (no meat, fish, dairy, eggs, nuts, gluten;
  `DietConfig.rules`, migration `0005`). Forbidden foods are removed from the model's list,
  from our own dishes (they used to borrow any food when short) and from the person's
  products, with a note. Four built-in dishes free of all six groups make a 3-day menu
  possible with any combination; a test covers all 63.
- Recipe checks (`core/recipe_check.py`, `services/recipe_mentions.py`): a recipe may not
  name a calorie-dense food missing from the dish (hidden calories), repeat amounts, or
  carry links, @accounts, e-mails or phone numbers (names too). The model gets the
  problems back and retries; every built-in recipe passes the same checks.

### Changed
- Parts of a measure are words, not fraction signs: "полстакана", "четверть пачки",
  "полтора половника", "2 с половиной стакана". "банка" is no longer read as "банк"
  ("5 банков").
- The food list in the prompt is compact ("6 Гречка (варёная): 8 половник ~100г; ..."):
  the full list is 7.7k characters instead of 14.4k, sent in up to 36 calls a menu. The
  prompt now states the new recipe rules.
- Every message the person sees was rewritten in one style: bold titles, highlighted numbers,
  examples in italics, "Шаг N из 6" in the questionnaire, icons on buttons and shopping
  sections, a readable profile ("32 года", values without button icons) and "Приятного
  аппетита!" after a menu. The bot always speaks to the person as "ты" and avoids slashed
  forms ("активна/активен", "Съела/съел") by rewording. After "не по плану" there is a "Составить
  меню" button instead of a bare command.
- All messages are now Telegram HTML (`bot.create_bot`, link previews off). Everything a person
  or the language model wrote is escaped with `render.html_text`; the test harness checks every
  sent message with a strict Telegram HTML validator (`tests/telegram_html.py`).
- Calories and macros now come from USDA FoodData Central (SR Legacy 2018-04) for 102 of 116
  foods: `src/nutrition_bot/data/food_sources.csv` names the USDA record of each food, and
  `scripts/import_usda.py` refreshes `foods.csv` from the download (git-ignored `data/usda/`).
  Cooked grains, pasta and legumes are the dry food divided by the yield factor, because USDA
  cooks them thinner. 14 Russian products (творог, кефир, сметана and others) keep their values
  until they are checked against labels. Notable changes: lean beef 230 -> 185 kcal and lean pork
  200 -> 143 kcal (cooked), cooked lentils 116 -> 141 kcal (the old value did not match the yield
  factor, so shopping lists were off).
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

### Fixed
- The bot log kept only warnings after startup: running migrations applied `alembic.ini`, which
  set the root logger to WARNING and replaced its handlers, so `LOG_LEVEL=INFO` was lost. Alembic
  now configures logging only when it is run from the command line.
- The menu time limit no longer starts an LLM call that is cancelled at once: asyncio may fire a
  timeout one clock tick early (15.6 ms on Windows), so less than a tick left counts as the
  deadline reached. This also fixes a test that failed now and then on Windows.

### Security
- CI jobs run with a read-only token (`permissions: contents: read`).
- A gitleaks pre-commit hook catches tokens and API keys before a commit, not only in CI.
- Removed `foxella-consent.patch`, a leftover diff committed by mistake (it held no secrets).

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
