"""All user-facing bot texts (Russian). Keep every message here, not in handlers."""

from nutrition_bot.core.balance import HintKind
from nutrition_bot.core.models import ActivityLevel, FoodCategory, Goal, MealType, Sex
from nutrition_bot.core.slip import SlipOutcome

START = "Привет! Я Фоксела 🦊 Помогу составить питание без весов и без чувства вины."
DISCLAIMER = "Я не заменяю врача и не ставлю диагнозов. Я предназначена для взрослых (18+)."

# Messages after a day that differed from the plan. The tone is always calm and kind: no blame,
# no "you should", no punishment. Placeholders: {excess_kcal}, {per_day_kcal} (whole numbers).
SLIP_TEXTS: dict[SlipOutcome, str] = {
    SlipOutcome.WITHIN_TOLERANCE: (
        "Это в пределах обычных колебаний, так что ничего менять не нужно. Продолжаем по плану 🙂"
    ),
    SlipOutcome.UNDER_PLAN: (
        "Сегодня получилось меньше плана. Ничего добирать не нужно, но и пропускать приёмы "
        "пищи ради этого не стоит: завтра просто возвращаемся к обычному меню."
    ),
    SlipOutcome.FULL: (
        "Всё в порядке, такое бывает. Сегодня вышло примерно на {excess_kcal} ккал больше "
        "плана. Мягко распределим это на ближайшие дни, около {per_day_kcal} ккал в день. "
        "Это совсем небольшая поправка, голодать не придётся."
    ),
    SlipOutcome.PARTIAL: (
        "Всё в порядке, такое бывает. Сегодня вышло примерно на {excess_kcal} ккал больше "
        "плана. Чтобы не урезать рацион, немного скорректируем только ближайшие дни "
        "(около {per_day_kcal} ккал в день), а остальное просто оставим как есть."
    ),
    SlipOutcome.NO_ROOM: (
        "Всё в порядке, такое бывает. Ничего менять не будем, просто продолжаем по плану."
    ),
}

# "What is missing" hints. Suggestions, not orders; no amounts are shown.
# Placeholder in PROTEIN_MEAL: {meal} (see MEAL_IN).
HINT_TEXTS: dict[HintKind, str] = {
    HintKind.VEG_FRUIT: (
        "Овощей и фруктов пока маловато. Попробуйте добавить к любому приёму пищи "
        "овощной салат, свежие овощи или фрукт: так больше клетчатки и дольше сытость."
    ),
    HintKind.PROTEIN_MEAL: (
        "В {meal} белка маловато. Хорошо подойдут яйца, творог, йогурт, рыба, курица или бобовые."
    ),
    HintKind.PROTEIN_DAY: (
        "Белка в рационе маловато. Хорошо подойдут яйца, творог, йогурт, рыба, курица или бобовые."
    ),
    HintKind.FIBER: (
        "Клетчатки может не хватать. Помогут цельнозерновой хлеб, бобовые и каши из цельных круп."
    ),
}

# Meal names after the preposition "в" (accusative), for the {meal} placeholder.
MEAL_IN: dict[MealType, str] = {
    MealType.BREAKFAST: "завтрак",
    MealType.LUNCH: "обед",
    MealType.DINNER: "ужин",
    MealType.SNACK: "перекус",
}

# Section titles of the shopping list.
SHOPPING_TITLES: dict[FoodCategory, str] = {
    FoodCategory.VEGETABLE: "Овощи",
    FoodCategory.FRUIT: "Фрукты",
    FoodCategory.MEAT: "Мясо и птица",
    FoodCategory.FISH: "Рыба",
    FoodCategory.EGG: "Яйца",
    FoodCategory.DAIRY: "Молочные продукты",
    FoodCategory.GRAIN: "Крупы и макароны",
    FoodCategory.STARCH: "Картофель и крахмалистое",
    FoodCategory.LEGUME: "Бобовые",
    FoodCategory.BREAD: "Хлеб",
    FoodCategory.NUT: "Орехи",
    FoodCategory.FAT: "Масло и жиры",
    FoodCategory.SAUCE: "Соусы",
    FoodCategory.SWEET: "Сладкое",
    FoodCategory.OTHER: "Другое",
}
SHOPPING_EMPTY = "В меню пока нет продуктов, поэтому список покупок пуст."

# ------------------------------------------------------------------ onboarding

WELCOME_BACK = (
    "С возвращением! Твои данные уже сохранены.\n"
    "/menu — составить меню, /shopping — список покупок, /slip — если что-то пошло не по плану, "
    "/profile — твои данные."
)
ASK_SEX = (
    "Давай познакомимся, это займёт минуту. Я посчитаю твою норму калорий и БЖУ.\n\n"
    "Для формулы мне нужен биологический пол:"
)
ASK_AGE = "Сколько тебе полных лет? Напиши числом, например: 32"
ASK_HEIGHT = "Какой у тебя рост в сантиметрах? Например: 168"
ASK_WEIGHT = "Сколько ты сейчас весишь, в килограммах? Например: 64,5"
ASK_ACTIVITY = "Насколько ты обычно активна/активен?"
ASK_GOAL = "И последнее: какая у тебя цель?"
BAD_NUMBER = "Не получилось разобрать число. Напиши, пожалуйста, например: {example}"
OUT_OF_RANGE = "Тут я ожидаю значение от {low} до {high}. Попробуй ещё раз."
UNDERAGE = (
    "Спасибо, что заглянул(а)! Я рассчитана только на взрослых (18+), поэтому норму считать "
    "не буду. Если хочется наладить питание, лучше сделать это вместе с родителями и врачом. "
    "Ничего из введённого я не сохранила."
)
INVALID_PROFILE = (
    "Что-то в данных выглядит нереалистично, и по ним я не смогу посчитать безопасную норму. "
    "Давай начнём заново: /start"
)
ONBOARDING_DONE = (
    "Готово! Вот твоя ориентировочная норма на день:\n"
    "🔥 {kcal} ккал\n"
    "🥩 белки {protein} г · 🥑 жиры {fat} г · 🍚 углеводы {carb} г\n\n"
    "Это расчёт по формуле, а не медицинская рекомендация: если есть заболевания или сомнения, "
    "сначала посоветуйся с врачом.\n\n"
    "Дальше можно составить меню. Взвешивать ничего не придётся: порции будут в половниках, "
    "грудках и ложках."
)

SEX_LABELS: dict[Sex, str] = {Sex.FEMALE: "Женщина", Sex.MALE: "Мужчина"}
ACTIVITY_LABELS: dict[ActivityLevel, str] = {
    ActivityLevel.SEDENTARY: "Почти не двигаюсь, сидячая работа",
    ActivityLevel.LIGHT: "Лёгкая: прогулки, 1–3 тренировки в неделю",
    ActivityLevel.MODERATE: "Средняя: 3–5 тренировок в неделю",
    ActivityLevel.HIGH: "Высокая: тренировки почти каждый день",
    ActivityLevel.VERY_HIGH: "Очень высокая: тяжёлый физический труд или спорт",
}
GOAL_LABELS: dict[Goal, str] = {
    Goal.LOSE: "Похудеть",
    Goal.MAINTAIN: "Держать форму",
    Goal.GAIN: "Набрать вес",
}

# ------------------------------------------------------------------------ menu

NEED_PROFILE = "Сначала давай познакомимся: нажми /start, это быстро."
MENU_ASK_DAYS = "На сколько дней составить меню?"
MENU_ASK_PRODUCTS = (
    "Какие продукты у тебя есть? Напиши списком, как удобно: «курица, рис, брокколи, 2 яйца, "
    "творог». Можно и неточно, я разберусь.\n\n"
    "Или выбери готовый вариант:"
)
MENU_PRODUCTS_AGAIN = (
    "Я не нашла в этом списке знакомых продуктов. Попробуй написать проще, через запятую: "
    "«гречка, куриная грудка, огурцы». Или нажми «Любые продукты»."
)
MENU_WORKING = "Составляю меню, это может занять до минуты…"
MENU_UNKNOWN_NOTE = "Этого в моей базе пока нет, пропускаю: {items}."
MENU_CLARIFY = "«{text}»: что именно имеется в виду?"
MENU_CLARIFY_ANY = "Любой из них"
MENU_CLARIFY_SKIP = "Пропустить"
MENU_EXTRA_NOTE = (
    "В меню попали несколько продуктов, которых не было в твоём списке. "
    "Они уже учтены в списке покупок."
)
MENU_MEASURE_NOTE = "Порции указаны в бытовых мерах, граммы считать не нужно."
MENU_EMPTY = "У меня не получилось собрать меню. Попробуй ещё раз через минуту: /menu"
# Menu messages are sent with Telegram HTML (<b>, <i>, <blockquote>); dynamic parts are escaped.
DAY_TITLE = "📅 <b>День {n}</b>\n🔥 {kcal} ккал · 🥩 Б {protein} · 🥑 Ж {fat} · 🍚 У {carb}"
MEAL_LINE = "{icon} <b>{title}</b> · ≈ {kcal} ккал\n<i>Б {protein} · Ж {fat} · У {carb}</i>"
RECIPE_LABEL = "👩‍🍳 <b>Как приготовить</b>\n"
HINTS_TITLE = "💡 Чего может не хватать:"
CATEGORY_ICONS: dict[FoodCategory, str] = {
    FoodCategory.GRAIN: "🌾",
    FoodCategory.STARCH: "🥔",
    FoodCategory.MEAT: "🍗",
    FoodCategory.FISH: "🐟",
    FoodCategory.EGG: "🥚",
    FoodCategory.DAIRY: "🥛",
    FoodCategory.VEGETABLE: "🥬",
    FoodCategory.FRUIT: "🍎",
    FoodCategory.LEGUME: "🫘",
    FoodCategory.NUT: "🥜",
    FoodCategory.FAT: "🫒",
    FoodCategory.BREAD: "🍞",
    FoodCategory.SWEET: "🍯",
    FoodCategory.SAUCE: "🥫",
    FoodCategory.OTHER: "🍽",
}
MEAL_TITLES: dict[MealType, str] = {
    MealType.BREAKFAST: "Завтрак",
    MealType.LUNCH: "Обед",
    MealType.SNACK: "Перекус",
    MealType.DINNER: "Ужин",
}
MEAL_ICONS: dict[MealType, str] = {
    MealType.BREAKFAST: "🍳",
    MealType.LUNCH: "🍲",
    MealType.SNACK: "🍎",
    MealType.DINNER: "🍽",
}

# -------------------------------------------------------------------- shopping

NO_MENU = "Сначала составим меню, по нему я соберу список покупок: /menu"
SHOPPING_HEADER = "🛒 Список покупок на {days} (то, что уже есть дома, я не включала)"
SHOPPING_NO_AMOUNT = "по потребности"
SHOPPING_STAPLES_TITLE = "🏠 Обычно есть дома, проверьте"

# ------------------------------------------------------------------------ slip

SLIP_ASK = (
    "Бывает, это нормально. Напиши, что было сверх меню или вместо него, например: "
    "«2 куска пиццы, пирожное». Если не хочешь перечислять, выбери примерный размер."
)
SLIP_UNKNOWN = "Этого я не знаю, не стала учитывать: {items}."
SLIP_NOTHING = "Из написанного я ничего не узнала. Можно перечислить проще или выбрать размер."
SLIP_CONFIRM = "Поняла так:\n{lines}\n\nПримерно {kcal} ккал сверх плана. Всё верно?"
SLIP_QUICK_LABELS: dict[str, str] = {
    "small": "Немного (перекус)",
    "medium": "Средне (как приём пищи)",
    "large": "Много (как большой обед)",
}
SLIP_NEXT_MENU = "Новое меню с этой поправкой: /menu"

# -------------------------------------------------------------- profile/delete

PROFILE_VIEW = (
    "👤 Твои данные\n"
    "Пол: {sex}\nВозраст: {age}\nРост: {height} см\nВес: {weight} кг\n"
    "Активность: {activity}\nЦель: {goal}\n\n"
    "🔥 Норма: {kcal} ккал · белки {protein} г · жиры {fat} г · углеводы {carb} г"
)
DELETE_CONFIRM = "Удалить все твои данные: профиль, список продуктов и меню? Это нельзя отменить."
DELETE_DONE = "Готово, всё удалено. Если захочешь вернуться, просто нажми /start."
DELETE_NOTHING = "У меня и так ничего о тебе не хранится."
CANCELLED = "Хорошо, ничего не меняю."
FALLBACK = "Я пока понимаю только команды: /start, /menu, /shopping, /slip, /profile, /delete_me."
ERROR_GENERIC = "Что-то пошло не так на моей стороне. Попробуй ещё раз чуть позже."

# ---------------------------------------------------------------------- buttons

BTN_MAKE_MENU = "🍽 Составить меню"
BTN_ANY_PRODUCTS = "Любые продукты"
BTN_LAST_PRODUCTS = "Как в прошлый раз"
BTN_SHOPPING = "🛒 Список покупок"
BTN_SLIP = "Съела/съел другое"
BTN_EDIT_PROFILE = "Изменить данные"
BTN_DELETE = "Удалить мои данные"
BTN_YES = "Да, верно"
BTN_REDO = "Нет, заново"
BTN_YES_DELETE = "Да, удалить всё"
BTN_CANCEL = "Отмена"
DAYS_LABELS: dict[int, str] = {1: "1 день", 2: "2 дня", 3: "3 дня"}
DAYS_ACCUSATIVE: dict[int, str] = {1: "1 день", 2: "2 дня", 3: "3 дня"}

BOT_COMMANDS: dict[str, str] = {
    "start": "Знакомство и расчёт нормы",
    "menu": "Составить меню",
    "shopping": "Список покупок",
    "slip": "Съела/съел другое",
    "profile": "Мои данные",
    "delete_me": "Удалить все мои данные",
}
SHOPPING_ALL_OWNED = (
    "Всё, что нужно для этого меню, у тебя уже есть. Покупать ничего не придётся 🎉"
)


# ---- Safety notes and the optional "check my target weight" step.
LOW_KCAL_NOTE = (
    "Обрати внимание: расчётная норма получилась ниже обычного минимума "
    "({minimum} ккал для {who}). Так бывает при небольшом весе, росте или малой подвижности. "
    "Лучше обсудить питание с врачом. Калории ниже расчётных я урезать не буду."
)
LOW_KCAL_WHO = {"male": "мужчин", "female": "женщин"}

BTN_CHECK_GOAL = "🎯 Проверить срок"
GOAL_ASK_TARGET = (
    "Какой вес хочешь получить? Напиши число в килограммах, например 65. "
    "Сейчас у тебя {weight} кг. Я оценю, за какой срок это безопасно."
)
GOAL_NOT_A_NUMBER = "Не получилось понять число. Напиши вес в килограммах, например 65 или 64,5."
GOAL_BAD_TARGET = (
    "Этот вес не подходит к твоей цели или выглядит нереалистично. При похудении целевой вес "
    "меньше текущего, при наборе больше. Напиши другое число в килограммах."
)
GOAL_ASK_WEEKS = "За сколько недель хочешь прийти к этому? Выбери вариант или напиши число."
GOAL_BAD_WEEKS = "Подойдёт срок от 1 до {max_weeks} недель. Выбери вариант или напиши число."
GOAL_NOT_NEEDED = (
    "Целевой вес нужен для похудения или набора. Сейчас у тебя цель «держать вес», "
    "так что проверять нечего."
)
GOAL_OK = (
    "Это реальный срок: около {pace} кг в неделю. Моя норма уже рассчитана на безопасный темп, "
    "так что можно спокойно идти по плану 🙂"
)
GOAL_TOO_FAST = (
    "Так быстро безопасно не получится: за {weeks_asked} нед. это {pace_asked} кг в неделю, "
    "а безопасно примерно {safe} кг в неделю. Реалистичный срок: около {weeks} нед. "
    "Норма, которую я посчитала, уже рассчитана на безопасный темп, менять ничего не нужно."
)
GOAL_NO_SAFE = (
    "С твоими данными безопасного плана для такого изменения веса я предложить не могу: "
    "калорий и так немного. Лучше обсудить цель с врачом."
)

# ---- Protection against spamming the menu button, and old buttons.
MENU_BUSY = "Меню ещё собирается, подожди немного 🙂"
MENU_COOLDOWN = "Давай немного подождём: новое меню можно составить через {seconds} с."
STALE_BUTTON = "Эта кнопка уже не работает. Начни заново командой /menu или /start."
