"""All user-facing bot texts (Russian). Keep every message here, not in handlers.

Every message is sent as Telegram HTML (see ``bot.create_bot``): only <b>, <i>, <u> and
<blockquote> are used here. Placeholders that receive text a person typed must be filled with
``render.html_text(...)``; numbers and our own labels are safe as they are.

Style: the bot is Фоксела (she: "поняла", "составила") and speaks to the person as "ты". Words
that would depend on the person's gender are avoided instead of written with a slash.
"""

from nutrition_bot.core.balance import HintKind
from nutrition_bot.core.models import ActivityLevel, FoodCategory, Goal, MealType, Sex
from nutrition_bot.core.slip import SlipOutcome

START = (
    "<b>Привет! Я Фоксела</b> 🦊\n\n"
    "Помогу питаться спокойно: посчитаю норму, составлю меню из того, что есть дома, "
    "и соберу список покупок. Порции в половниках и ложках, без весов и без чувства вины."
)
DISCLAIMER = (
    "<blockquote>Я не заменяю врача и не ставлю диагнозов. "
    "Я рассчитана на взрослых (18+).</blockquote>"
)
BTN_CONSENT = "✅ Понятно, мне есть 18"
CONSENT_REMINDER = "Чтобы начать, нажми кнопку «Понятно» под приветствием 🙂"

# Messages after a day that differed from the plan. The tone is always calm and kind: no blame,
# no "you should", no punishment. Placeholders: {excess_kcal}, {per_day_kcal} (whole numbers).
SLIP_TEXTS: dict[SlipOutcome, str] = {
    SlipOutcome.WITHIN_TOLERANCE: (
        "Это в пределах обычных колебаний, так что ничего менять не нужно. Продолжаем по плану 🙂"
    ),
    SlipOutcome.UNDER_PLAN: (
        "Сегодня получилось меньше плана. Ничего добирать не нужно, но и пропускать приёмы "
        "пищи ради этого не стоит: завтра просто возвращаемся к обычному меню 🌱"
    ),
    SlipOutcome.FULL: (
        "Всё в порядке, такое бывает 💛\n\n"
        "Сегодня вышло примерно на <b>{excess_kcal} ккал</b> больше плана. Мягко распределим "
        "это на ближайшие дни, около <b>{per_day_kcal} ккал</b> в день. Это совсем небольшая "
        "поправка, голодать не придётся."
    ),
    SlipOutcome.PARTIAL: (
        "Всё в порядке, такое бывает 💛\n\n"
        "Сегодня вышло примерно на <b>{excess_kcal} ккал</b> больше плана. Чтобы не урезать "
        "рацион, немного скорректируем только ближайшие дни (около <b>{per_day_kcal} ккал</b> "
        "в день), а остальное просто оставим как есть."
    ),
    SlipOutcome.NO_ROOM: (
        "Всё в порядке, такое бывает 💛 Ничего менять не будем, просто продолжаем по плану."
    ),
}

# "What is missing" hints. Suggestions, not orders; no amounts are shown.
# Placeholder in PROTEIN_MEAL: {meal} (see MEAL_IN).
HINT_TEXTS: dict[HintKind, str] = {
    HintKind.VEG_FRUIT: (
        "Овощей и фруктов пока маловато. Попробуй добавить к любому приёму пищи "
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

# Section titles of the shopping list (the icon comes from CATEGORY_ICONS).
SHOPPING_TITLES: dict[FoodCategory, str] = {
    FoodCategory.VEGETABLE: "Овощи",
    FoodCategory.FRUIT: "Фрукты и ягоды",
    FoodCategory.MEAT: "Мясо и птица",
    FoodCategory.FISH: "Рыба и морепродукты",
    FoodCategory.EGG: "Яйца",
    FoodCategory.DAIRY: "Молочные продукты",
    FoodCategory.GRAIN: "Крупы и макароны",
    FoodCategory.STARCH: "Картофель и крахмалистое",
    FoodCategory.LEGUME: "Бобовые",
    FoodCategory.BREAD: "Хлеб",
    FoodCategory.NUT: "Орехи и семечки",
    FoodCategory.FAT: "Масло и жиры",
    FoodCategory.SAUCE: "Соусы",
    FoodCategory.SWEET: "Сладкое",
    FoodCategory.DISH: "Готовые блюда",
    FoodCategory.OTHER: "Другое",
}
SHOPPING_EMPTY = "В меню пока нет продуктов, поэтому список покупок пуст."

# ------------------------------------------------------------------ onboarding

WELCOME_BACK = "С возвращением! 🦊 Твои данные на месте. Что делаем? Кнопки внизу 👇"
# The permanent panel under the input field; the labels are also what the handlers listen for.
BTN_NAV_MENU = "🍽 Меню"
BTN_NAV_SHOPPING = "🛒 Покупки"
BTN_NAV_SLIP = "🔄 Не по плану"
BTN_NAV_PROFILE = "👤 Профиль"
NAV_LABELS = (BTN_NAV_MENU, BTN_NAV_SHOPPING, BTN_NAV_SLIP, BTN_NAV_PROFILE)
NAV_HINT = (
    "👇 Кнопки внизу теперь всегда под рукой: меню, покупки, «Не по плану» и профиль "
    "в одно касание."
)
ASK_SEX = (
    "Давай познакомимся, это займёт минуту ⏱\n"
    "Я посчитаю твою норму калорий и БЖУ.\n\n"
    "<b>Шаг 1 из 6.</b> Для формулы мне нужен биологический пол:"
)
ASK_AGE = "<b>Шаг 2 из 6.</b> Сколько тебе полных лет?\n<i>Например: 32</i>"
ASK_HEIGHT = "<b>Шаг 3 из 6.</b> Какой у тебя рост в сантиметрах?\n<i>Например: 168</i>"
ASK_WEIGHT = "<b>Шаг 4 из 6.</b> Сколько ты сейчас весишь, в килограммах?\n<i>Например: 64,5</i>"
ASK_ACTIVITY = "<b>Шаг 5 из 6.</b> Сколько движения в твоей обычной неделе?"
ASK_GOAL = "<b>Шаг 6 из 6.</b> И последнее: какая у тебя цель?"
BAD_NUMBER = "Не получилось разобрать число 🤔 Напиши просто цифрами, например: <b>{example}</b>"
OUT_OF_RANGE = "Тут я жду значение <b>от {low} до {high}</b>. Попробуй ещё раз 🙂"
UNDERAGE = (
    "Спасибо за доверие 💛 Я рассчитана только на взрослых (18+), поэтому норму считать "
    "не буду. Если хочется наладить питание, лучше сделать это вместе с родителями и врачом.\n\n"
    "Ничего из введённого я не сохранила."
)
INVALID_PROFILE = (
    "Что-то в данных выглядит нереалистично, и по ним я не смогу посчитать безопасную норму 🤔\n"
    "Давай начнём заново: /start"
)
ONBOARDING_DONE = (
    "🎉 <b>Готово! Твоя норма на день</b>\n\n"
    "🔥 <b>{kcal} ккал</b>\n"
    "🥩 Белки: <b>{protein} г</b>\n"
    "🥑 Жиры: <b>{fat} г</b>\n"
    "🍚 Углеводы: <b>{carb} г</b>\n\n"
    "<i>Это расчёт по формуле, а не медицинская рекомендация. Если есть заболевания "
    "или сомнения, сначала посоветуйся с врачом.</i>\n\n"
    "Дальше составим меню. Взвешивать ничего не придётся: порции будут в половниках, "
    "грудках и ложках 🥄"
)

SEX_LABELS: dict[Sex, str] = {Sex.FEMALE: "👩 Женщина", Sex.MALE: "👨 Мужчина"}
ACTIVITY_LABELS: dict[ActivityLevel, str] = {
    ActivityLevel.SEDENTARY: "🛋 Почти не двигаюсь, сидячая работа",
    ActivityLevel.LIGHT: "🚶 Лёгкая: прогулки, 1–3 тренировки в неделю",
    ActivityLevel.MODERATE: "🏃 Средняя: 3–5 тренировок в неделю",
    ActivityLevel.HIGH: "🏋 Высокая: тренировки почти каждый день",
    ActivityLevel.VERY_HIGH: "⚡ Очень высокая: тяжёлый физический труд или спорт",
}
GOAL_LABELS: dict[Goal, str] = {
    Goal.LOSE: "📉 Похудеть",
    Goal.MAINTAIN: "⚖️ Держать форму",
    Goal.GAIN: "📈 Набрать вес",
}

# ------------------------------------------------------------------------ menu

NEED_PROFILE = "Сначала давай познакомимся 🦊 Нажми /start, это займёт минуту."
MENU_ASK_DAYS = "🗓 <b>На сколько дней составить меню?</b>"
MENU_ASK_PRODUCTS = (
    "🧺 <b>Что есть дома?</b>\n\n"
    "Напиши списком, как удобно:\n"
    "<i>курица, рис, брокколи, 2 яйца, творог</i>\n\n"
    "Можно неточно, я разберусь. Или выбери вариант ниже 👇"
)
MENU_PRODUCTS_AGAIN = (
    "Не нашла в этом списке знакомых продуктов 🤔 Попробуй проще, через запятую:\n"
    "<i>гречка, куриная грудка, огурцы</i>\n\n"
    "Или нажми «Любые продукты»."
)
MENU_WORKING = "👩‍🍳 Составляю меню, это займёт до минуты…"
# {items}: what the person typed, escaped.
MENU_UNKNOWN_NOTE = "Этого пока нет в моей базе, пропускаю: <i>{items}</i>"
# {text}: what the person typed, escaped.
MENU_CLARIFY = "Уточни, пожалуйста: «<b>{text}</b>» это что именно?"
# {items}: "курица → Куриная грудка (сырая)" pairs, escaped.
CHOICE_REMEMBERED = (
    "🧠 Взяла как в прошлый раз: <i>{items}</i>. "
    "Если сейчас другое, напиши точнее, например «куриное бедро»."
)
MENU_CLARIFY_ANY = "Любой из них"
MENU_CLARIFY_SKIP = "Пропустить"
MENU_EXTRA_NOTE = (
    "В меню попали несколько продуктов, которых не было в твоём списке. "
    "Они уже учтены в списке покупок."
)
MENU_MEASURE_NOTE = "Порции указаны в бытовых мерах, граммы считать не нужно 🥄"
MENU_DONE = "Приятного аппетита! 🦊 Что дальше?"
MENU_EMPTY = "Не получилось собрать меню 😔 Попробуй ещё раз через минуту: /menu"
DAY_TITLE = "📅 <b>День {n}</b>\n🔥 <b>{kcal} ккал</b> · 🥩 Б {protein} · 🥑 Ж {fat} · 🍚 У {carb}"
MEAL_LINE = "{icon} <b>{title}</b> · ≈ {kcal} ккал\n<i>Б {protein} · Ж {fat} · У {carb}</i>"
DISH_KCAL = " <i>· ≈ {kcal} ккал</i>"
RECIPE_LABEL = "👩‍🍳 <b>Как приготовить</b>\n"
HINTS_TITLE = "💡 <b>Чего может не хватать</b>"
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
    FoodCategory.DISH: "🍲",
    FoodCategory.OTHER: "🍽",
}
# The icon of one food in menus and the shopping list: the first rule with the food's code or
# a prefix of it up to "_" wins ("pear" fits "pear", not "pearl_barley"); foods without a rule
# get their category icon. Order matters: "egg_noodles" before "egg", "potato_chips" before
# "potato". Only emoji that phones have shown for years (no pea pod or ginger root: older
# phones draw an empty box).
FOOD_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    # ready dishes first: their codes start with the names of their foods
    (("chicken_noodle_soup", "pea_soup", "fish_soup", "borscht", "shchi", "solyanka",
      "okroshka", "veg_stew", "goulash", "meatballs", "golubtsy"), "🍲"),
    (("pizza",), "🍕"),
    (("hamburger", "cheeseburger"), "🍔"),
    (("french_fries", "potato_chips"), "🍟"),
    (("chicken_nuggets",), "🍗"),
    (("hot_dog", "sausages_boiled", "sardelki"), "🌭"),
    (("pelmeni", "vareniki", "chebureki", "samsa", "pirozhok"), "🥟"),
    (("bliny", "syrniki", "draniki"), "🥞"),
    (("sandwich",), "🥪"),
    (("shawarma",), "🌯"),
    (("olivier", "vinegret", "caesar", "greek_salad", "herring_under_fur"), "🥗"),
    (("plov",), "🍛"),
    (("roll",), "🍣"),
    (("lasagna", "spaghetti", "navy_pasta", "pasta"), "🍝"),
    (("egg_noodles", "instant_noodles"), "🍜"),
    (("omelet", "fried_eggs"), "🍳"),
    (("cake", "cheesecake", "apple_pie", "cottage_casserole"), "🍰"),
    (("ice_cream",), "🍦"),
    (("donut",), "🍩"),
    (("croissant",), "🥐"),
    # drinks
    (("tea",), "🍵"),
    (("coffee", "latte"), "☕"),
    (("beer", "kvass"), "🍺"),
    (("wine",), "🍷"),
    (("vodka",), "🥃"),
    (("juice", "nectar", "mors", "compote", "tomato_juice"), "🧃"),
    (("cola", "diet_soda", "energy_drink", "milkshake"), "🥤"),
    (("cocoa", "milk_chocolate", "dark_chocolate", "chocolate", "hazelnut_spread",
      "protein_bar"), "🍫"),
    # vegetables
    (("cucumber", "pickles", "zucchini", "squash_caviar"), "🥒"),
    (("tomato", "tomatoes", "ketchup"), "🍅"),
    (("korean_carrot", "carrot"), "🥕"),
    (("sweet_potato",), "🍠"),
    (("potato", "mashed_potato", "fried_potato"), "🥔"),
    (("onion", "green_onion"), "🧅"),
    (("garlic",), "🧄"),
    (("bell_pepper", "lecho"), "🫑"),
    (("broccoli", "cauliflower"), "🥦"),
    (("eggplant",), "🍆"),
    (("corn",), "🌽"),
    (("mushrooms", "oyster_mushrooms", "chanterelles"), "🍄"),
    (("greens_herbs", "arugula", "spinach"), "🌿"),
    (("asparagus", "peas", "green_beans"), "🌱"),
    (("pumpkin_seeds", "pumpkin"), "🎃"),
    (("olives", "olive_oil"), "🫒"),
    (("avocado",), "🥑"),
    # fruit and berries
    (("apple",), "🍎"),
    (("pear",), "🍐"),
    (("banana",), "🍌"),
    (("orange", "mandarin", "grapefruit", "pomelo"), "🍊"),
    (("lemon", "lime"), "🍋"),
    (("grapes", "raisins"), "🍇"),
    (("kiwi",), "🥝"),
    (("strawberry", "raspberry", "cranberry", "gooseberry"), "🍓"),
    (("blueberry", "blackcurrant", "blackberry", "plum", "prunes"), "🫐"),
    (("cherry",), "🍒"),
    (("peach", "apricot", "nectarine", "dried_apricots"), "🍑"),
    (("watermelon",), "🍉"),
    (("melon",), "🍈"),
    (("pineapple",), "🍍"),
    (("mango",), "🥭"),
    (("coconut",), "🥥"),
    # grains and bread
    (("rice",), "🍚"),
    (("buckwheat", "oat", "oatmeal", "millet", "bulgur", "couscous", "quinoa", "pearl_barley",
      "semolina", "granola"), "🥣"),
    (("pita", "lavash"), "🫓"),
    (("sushki",), "🥯"),
    (("bread", "crispbread"), "🍞"),
    # meat, fish, eggs
    (("chicken", "drumstick", "turkey", "duck"), "🍗"),
    (("salo", "bacon"), "🥓"),
    (("ham", "doctor_sausage", "salami", "servelat", "smoked_chicken"), "🍖"),
    (("beef", "pork", "lamb", "minced", "shashlik", "stewed_beef"), "🥩"),
    (("shrimp",), "🍤"),
    (("crab_sticks",), "🦀"),
    (("squid",), "🦑"),
    (("mussels",), "🦪"),
    (("egg",), "🥚"),
    # dairy
    (("cream_cheese", "cheese", "mozzarella", "feta", "parmesan", "ricotta",
      "processed_cheese", "adyghe"), "🧀"),
    (("butter", "ghee"), "🧈"),
    (("condensed",), "🥛"),
    # nuts, seeds, sweets
    (("peanuts", "peanut_butter"), "🥜"),
    (("walnuts", "hazelnuts", "almonds", "cashew", "brazil_nuts", "pine_nuts", "pistachio"),
     "🌰"),
    (("sunflower",), "🌻"),
    (("honey", "jam"), "🍯"),
    (("cookie", "pryanik"), "🍪"),
    (("wafers",), "🧇"),
    (("sugar", "powdered_sugar", "zefir", "pastila", "marmalade", "halva"), "🍬"),
    (("beans", "white_beans", "red_beans", "lentils", "chickpeas", "split_peas", "hummus",
      "tofu"), "🫘"),
)  # fmt: skip
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

NO_MENU = "Сначала составим меню 🍽 По нему я соберу список покупок: /menu"
SHOPPING_HEADER = "🛒 <b>Список покупок на {days}</b>\n<i>То, что уже есть дома, я не включала.</i>"
SHOPPING_NO_AMOUNT = "по необходимости"
SHOPPING_STAPLES_TITLE = "🏠 <b>Обычно есть дома, проверь</b>"

# ------------------------------------------------------------------------ slip

SLIP_ASK = (
    "🔄 <b>Бывает, это нормально</b>\n\n"
    "Напиши, что было сверх меню или вместо него:\n"
    "<i>2 куска пиццы, пирожное</i>\n\n"
    "Не хочется перечислять? Выбери примерный размер 👇"
)
# {items}: what the person typed, escaped.
SLIP_UNKNOWN = "Этого я не знаю, не стала учитывать: <i>{items}</i>"
SLIP_GUESSING = (
    "🔎 Такого нет в моей базе: <i>{items}</i>. Сейчас прикину, из чего это обычно состоит…"
)
SLIP_GUESSED = (
    "🤖 <i>{items}</i>: разложила на продукты по типичному рецепту, это примерная оценка. "
    "Если не похоже, нажми «Нет, заново» и напиши по-другому."
)
SLIP_NOTHING = "Из написанного я ничего не узнала 🤔 Можно перечислить проще или выбрать размер 👇"
SLIP_CONFIRM = (
    "📝 <b>Поняла так:</b>\n{lines}\n\nВсего примерно <b>{kcal} ккал</b>.\n"
    "Это было <b>сверх плана</b> или <b>вместо</b> одного из приёмов пищи? 👇"
)
BTN_SLIP_EXTRA = "➕ Сверх плана"
SLIP_INSTEAD_LABELS: dict[MealType, str] = {
    MealType.BREAKFAST: "🔁 Вместо завтрака",
    MealType.LUNCH: "🔁 Вместо обеда",
    MealType.SNACK: "🔁 Вместо перекуса",
    MealType.DINNER: "🔁 Вместо ужина",
}
# {meal}: a SLIP_INSTEAD_MEAL value; {kcal}: that meal in the plan, a whole number.
SLIP_INSTEAD_NOTE = "Учла, что это было вместо {meal} (по плану около {kcal} ккал)."
SLIP_INSTEAD_MEAL: dict[MealType, str] = {
    MealType.BREAKFAST: "завтрака",
    MealType.LUNCH: "обеда",
    MealType.SNACK: "перекуса",
    MealType.DINNER: "ужина",
}
SLIP_QUICK_LABELS: dict[str, str] = {
    "small": "🍪 Немного (перекус)",
    "medium": "🍝 Средне (как приём пищи)",
    "large": "🍱 Много (как большой обед)",
}
SLIP_NEXT_MENU = "Следующее меню уже учтёт эту поправку 👇"

# -------------------------------------------------------------- profile/delete

PROFILE_VIEW = (
    "👤 <b>Твой профиль</b>\n\n"
    "Пол: <b>{sex}</b>\n"
    "Возраст: <b>{age}</b>\n"
    "Рост: <b>{height} см</b>\n"
    "Вес: <b>{weight} кг</b>\n"
    "Активность: <b>{activity}</b>\n"
    "Цель: <b>{goal}</b>\n\n"
    "🔥 <b>Норма на день: {kcal} ккал</b>\n"
    "🥩 Б {protein} г · 🥑 Ж {fat} г · 🍚 У {carb} г"
)
# Profile values without the button icons: "Пол: 👩 Женщина" reads worse than "Пол: Женщина".
SEX_NAMES: dict[Sex, str] = {Sex.FEMALE: "женщина", Sex.MALE: "мужчина"}
ACTIVITY_NAMES: dict[ActivityLevel, str] = {
    ActivityLevel.SEDENTARY: "почти без движения",
    ActivityLevel.LIGHT: "лёгкая",
    ActivityLevel.MODERATE: "средняя",
    ActivityLevel.HIGH: "высокая",
    ActivityLevel.VERY_HIGH: "очень высокая",
}
GOAL_NAMES: dict[Goal, str] = {
    Goal.LOSE: "похудеть",
    Goal.MAINTAIN: "держать форму",
    Goal.GAIN: "набрать вес",
}
YEARS_FORMS = ("год", "года", "лет")
DELETE_CONFIRM = (
    "🗑 <b>Удалить все твои данные?</b>\n\n"
    "Профиль, список продуктов и меню исчезнут насовсем, отменить это будет нельзя."
)
DELETE_DONE = "✅ Готово, всё удалено. Захочешь вернуться: просто нажми /start 🦊"
DELETE_NOTHING = "У меня и так ничего о тебе не хранится 🙂"
CANCELLED = "👌 Хорошо, ничего не меняю."
FALLBACK = (
    "Я пока понимаю только кнопки внизу и команды 🙂\n\n"
    "/menu · составить меню\n"
    "/shopping · список покупок\n"
    "/slip · было не по плану\n"
    "/profile · мои данные\n"
    "/start · начать заново\n"
    "/delete_me · удалить мои данные"
)
ERROR_GENERIC = "😔 Что-то пошло не так на моей стороне. Попробуй ещё раз чуть позже."

# ---------------------------------------------------------------------- buttons

BTN_MAKE_MENU = "🍽 Составить меню"
BTN_ANY_PRODUCTS = "✨ Любые продукты"
BTN_LAST_PRODUCTS = "🔁 Как в прошлый раз"
BTN_SHOPPING = "🛒 Список покупок"
BTN_SLIP = "🔄 Было не по плану"
BTN_EDIT_PROFILE = "✏️ Изменить данные"
BTN_DELETE = "🗑 Удалить мои данные"
BTN_YES = "✅ Да, верно"
BTN_REDO = "↩️ Нет, заново"
BTN_YES_DELETE = "🗑 Да, удалить всё"
BTN_CANCEL = "↩️ Отмена"
DAYS_LABELS: dict[int, str] = {1: "1 день", 2: "2 дня", 3: "3 дня"}
DAYS_ACCUSATIVE: dict[int, str] = {1: "1 день", 2: "2 дня", 3: "3 дня"}
WEEKS_LABEL = "{n} нед."

BOT_COMMANDS: dict[str, str] = {
    "start": "Знакомство и расчёт нормы",
    "menu": "Составить меню",
    "shopping": "Список покупок",
    "slip": "Было не по плану",
    "profile": "Мои данные",
    "delete_me": "Удалить все мои данные",
}
SHOPPING_ALL_OWNED = (
    "🎉 Всё, что нужно для этого меню, у тебя уже есть. Покупать ничего не придётся!"
)


# ---- Safety notes and the optional "check my target weight" step.
LOW_KCAL_NOTE = (
    "⚠️ <b>Обрати внимание</b>\n"
    "Расчётная норма получилась ниже обычного минимума ({minimum} ккал для {who}). "
    "Так бывает при небольшом весе, росте или малой подвижности. Лучше обсудить питание "
    "с врачом. Калории ниже расчётных я урезать не буду."
)
LOW_KCAL_WHO = {"male": "мужчин", "female": "женщин"}

BTN_CHECK_GOAL = "🎯 За какой срок я дойду до цели?"
GOAL_ASK_TARGET = (
    "🎯 <b>Давай прикинем срок</b>\n\n"
    "Посмотрим, за какое время твоя цель реальна и безопасна. Сейчас у тебя "
    "<b>{weight} кг</b>. Сколько хочешь весить?\n"
    "<i>Напиши число в килограммах</i>"
)
GOAL_NOT_A_NUMBER = (
    "Не получилось понять число 🤔 Напиши вес в килограммах, например <b>65</b> или <b>64,5</b>."
)
GOAL_BAD_TARGET = (
    "Этот вес не подходит к твоей цели или выглядит нереалистично 🤔 При похудении подойдёт "
    "вес меньше текущего, при наборе больше. Напиши другое число в килограммах."
)
GOAL_ASK_WEEKS = (
    "Отлично! За сколько недель хочешь к этому прийти? Выбери кнопкой или напиши число."
)
GOAL_BAD_WEEKS = "Подойдёт срок от 1 до {max_weeks} недель. Выбери кнопкой или напиши число."
GOAL_NOT_NEEDED = (
    "Целевой вес нужен для похудения или набора. Сейчас у тебя цель «держать форму», "
    "так что проверять нечего 🙂"
)
GOAL_OK = (
    "🎉 <b>Отличный план!</b>\n\n"
    "Это около <b>{pace} кг в неделю</b>: спокойный и безопасный темп. Менять ничего не "
    "нужно, твоя норма уже рассчитана именно на такой темп."
)
GOAL_TOO_FAST = (
    "⏳ <b>Давай чуть спокойнее</b>\n\n"
    "За {weeks_asked} нед. выйдет {pace_asked} кг в неделю, а это слишком быстро. "
    "Безопасно примерно <b>{safe} кг в неделю</b>.\n\n"
    "🎯 Реалистичный срок: <b>около {weeks} нед.</b> Норму менять не нужно, она уже "
    "посчитана на безопасный темп. Просто идём к цели спокойнее 🦊"
)
GOAL_NO_SAFE = (
    "С твоими данными я не смогу предложить безопасный план для такого изменения веса: "
    "калорий и так немного. Лучше обсудить цель с врачом 💛"
)

# ---- Food restrictions (allergies, diets). Codes are the keys of ``DietConfig.rules``.
BTN_RESTRICTIONS = "🚫 Ограничения в еде"
RESTRICTION_LABELS: dict[str, str] = {
    "meat": "Без мяса",
    "fish": "Без рыбы и морепродуктов",
    "dairy": "Без молочного",
    "eggs": "Без яиц",
    "nuts": "Без орехов",
    "gluten": "Без глютена",
}
RESTRICTION_ON = "✅ {label}"
RESTRICTION_OFF = "▫️ {label}"
BTN_RESTRICTIONS_DONE = "Готово"
RESTRICTIONS_ASK = (
    "🚫 <b>Ограничения в еде</b>\n\n"
    "Отметь, чего не должно быть в меню. Можно выбрать несколько пунктов, потом нажми "
    "«Готово».\n\n"
    "<i>Я убираю такие продукты из меню целиком, но не знаю, что внутри конкретной упаковки. "
    "При аллергии всё равно проверяй состав хлеба, колбасы и соусов.</i>"
)
RESTRICTIONS_SAVED = "✅ Запомнила: <b>{items}</b>. Таких продуктов в меню больше не будет."
RESTRICTIONS_NONE = "✅ Ограничений нет: в меню может быть всё."
PROFILE_RESTRICTIONS = "\n\n🚫 Ограничения: <b>{items}</b>"
# {items}: names of foods from our own catalog.
MENU_RESTRICTED_NOTE = "Убрала из списка то, чего ты не ешь: <i>{items}</i>"
MENU_EMPTY_RESTRICTED = (
    "С такими ограничениями мне не хватило блюд для меню 😔 Попробуй назвать больше "
    "продуктов или выбрать «Любые продукты»."
)

# ---- Protection against spamming the menu button, and old buttons.
MENU_BUSY = "⏳ Меню ещё собирается, подожди немного 🙂"
MENU_COOLDOWN = "⏳ Давай чуть подождём: новое меню можно составить через {seconds} с."
STALE_BUTTON = "Эта кнопка уже не работает 🙂 Начни заново командой /menu или /start."


# --- /admin: the owner's statistics (only counts, never who) ---

ADMIN_TITLE = "📊 <b>Статистика Foxella</b>\n<i>{now} UTC · сутки, 7 и 30 дней назад до сейчас</i>"
ADMIN_USERS = "👥 <b>Пользователи</b>\nВсего: <b>{total}</b>\nНовых: {day} · {week} · {month}"
ADMIN_ACTIVE = "🔥 <b>Активные</b>\n{day} · {week} · {month}"
ADMIN_ACTIONS_TITLE = "🍽 <b>За неделю</b>"
ADMIN_ACTION_LINE = "{label}: {times} (людей: {people})"
ADMIN_ACTION_LABELS: dict[str, str] = {
    "onboarding_done": "Прошли знакомство",
    "menu_received": "Получили меню",
    "shopping_received": "Списки покупок",
    "slip_pressed": "«Было не по плану»",
}
ADMIN_RETURNS_TITLE = "🔁 <b>Возвращаются</b>"
ADMIN_RETURN_LINE = "На {week}-й неделе: {returned} из {eligible} ({share} %)"
ADMIN_RETURN_NOBODY = "На {week}-й неделе: пока никто не дошёл"
ADMIN_PEOPLE_TITLE = "🎯 <b>Кто они</b>"
ADMIN_GOALS = "Похудеть {lose} · держать форму {maintain} · набрать {gain}"
ADMIN_SEXES = "Женщин {female} · мужчин {male}"
ADMIN_RESTRICTIONS = "С ограничениями в еде: {count}"
ADMIN_LLM_ON = "🤖 ИИ подключён: <code>{model}</code>"
ADMIN_LLM_OFF = "🤖 ИИ не подключён: меню из встроенных блюд"
ADMIN_NOTE = (
    "<i>Активные — те, кто прошёл знакомство, получил меню или список покупок либо отметил"
    " «было не по плану». Кто удалил свои данные, в счёт не идёт.</i>"
)
BTN_ADMIN_REFRESH = "🔄 Обновить"
