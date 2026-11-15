"""Application settings and tunable constants.

Formula coefficients and safety thresholds live here, not inside functions.
Values marked ASSUMPTION were approved by the project owner in Stage 1.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WELCOME_IMAGE = Path(__file__).resolve().parent / "assets" / "welcome.jpg"
DATA_DIR = Path(__file__).resolve().parent / "data"


class NormsConfig(BaseModel):
    """Constants for calorie and macro norms (used by ``core.norms``)."""

    activity_factors: dict[str, float] = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "high": 1.725,
        "very_high": 1.9,
    }
    min_age: int = 18  # ASSUMPTION: adults only
    max_age: int = 100
    lose_deficit: float = 0.15  # default deficit for "lose"
    max_deficit: float = 0.20  # ASSUMPTION: hard cap on deficit
    gain_surplus: float = 0.10  # ASSUMPTION: moderate surplus
    min_kcal_female: float = 1200.0  # ASSUMPTION: absolute floor
    min_kcal_male: float = 1500.0  # ASSUMPTION: absolute floor

    # Plausible input ranges; anything outside is rejected as unrealistic data.
    min_height_cm: float = 120.0  # ASSUMPTION
    max_height_cm: float = 230.0  # ASSUMPTION
    min_weight_kg: float = 30.0  # ASSUMPTION
    max_weight_kg: float = 300.0  # ASSUMPTION

    # Mifflin-St Jeor: 10*kg + 6.25*cm - 5*age + offset (male +5, female -161).
    bmr_weight_coef: float = 10.0
    bmr_height_coef: float = 6.25
    bmr_age_coef: float = 5.0
    bmr_male_offset: float = 5.0
    bmr_female_offset: float = -161.0

    # Macros. ASSUMPTION: protein g per kg of body weight by goal.
    protein_g_per_kg: dict[str, float] = {"lose": 1.8, "maintain": 1.4, "gain": 1.6}
    max_protein_share: float = 0.30  # ASSUMPTION: protein never above 30 % of kcal
    fat_share: float = 0.28  # ASSUMPTION: fat is 28 % of kcal
    kcal_per_g_protein: float = 4.0  # Atwater factors
    kcal_per_g_carb: float = 4.0
    kcal_per_g_fat: float = 9.0

    # Weight-goal pace check (core.norms.check_weight_goal).
    kcal_per_kg_body_change: float = 7700.0  # ASSUMPTION: energy value of 1 kg of body mass
    max_goal_weeks: int = 104  # ASSUMPTION: goals longer than 2 years are rejected


class SlipConfig(BaseModel):
    """Constants for recalculation after a day off-plan (used by ``core.slip``)."""

    spread_days: int = 3  # ASSUMPTION: spread correction over 3 days
    max_daily_correction: float = 0.10  # ASSUMPTION: at most 10 % of daily norm per day
    ignore_below: float = 0.05  # ASSUMPTION: excess under 5 % of norm is ignored
    # ASSUMPTION: rough size of "something extra" for people who do not want to list foods.
    quick_kcal: dict[str, float] = {"small": 200.0, "medium": 500.0, "large": 900.0}


# Measures that are whole pieces: nobody eats 0.5 of an egg or 1¼ bananas. Their quantities are
# always whole numbers (step 1) in menus and in the shopping list. Names are ``measures.csv``
# ``name_ru`` values. Deliberately left out: things that are naturally halved or cut (a chicken
# breast, a steak, a slice, half an avocado, a large zucchini).
WHOLE_PIECE_MEASURES: tuple[str, ...] = (
    "яйцо",
    "помидор",
    "огурец",
    "перец",
    "морковь",
    "луковица",
    "свёкла",
    "картофелина",
    "клубень",
    "яблоко",
    "груша",
    "персик",
    "банан",
    "апельсин",
    "мандарин",
    "киви",
    "шампиньон",
    "сосиска",
    "котлета",
    "лепёшка",
    "зубчик",
    "штука",
)


class MenuConfig(BaseModel):
    """Constants for menu validation and portion fitting (used by ``core.menu``)."""

    meal_tolerance: float = 0.10  # ASSUMPTION: +-10 % of the per-meal kcal target
    max_llm_retries: int = 2  # retries after the first attempt, so at most 3 LLM calls per meal
    # ASSUMPTION: share of the daily kcal per meal; normalised over the meals actually planned.
    meal_shares: dict[str, float] = {
        "breakfast": 0.25,
        "lunch": 0.35,
        "dinner": 0.30,
        "snack": 0.10,
    }
    min_scale: float = 0.5  # LLM portions may be scaled by 0.5x ...
    max_scale: float = 2.0  # ... to 2x; a dish further off is sent back to the LLM
    fallback_min_scale: float = 0.3  # our own fallback dishes may be scaled more freely
    fallback_max_scale: float = 3.0
    quantity_steps: tuple[float, ...] = (0.5, 0.25)  # household quantities are rounded to these
    # ... but the finer step (a quarter) only for measures where "¼" is natural in speech; a
    # quarter of a bunch, a pack or a ladle sounds odd, so those stay on whole and half numbers.
    fine_measures: tuple[str, ...] = ("стакан", "столовая ложка", "чайная ложка")
    # ... except whole-piece measures (eggs, tomatoes, ...), which always use step 1.
    whole_measures: tuple[str, ...] = WHOLE_PIECE_MEASURES
    max_dishes_per_meal: int = 3
    max_items_per_dish: int = 10
    max_quantity: float = 20.0  # at most 20 household measures of one food
    max_name_length: int = 100
    max_days: int = 3  # the bot plans 1 to 3 days
    # Order of meals in a planned day (MealType values).
    meal_order: tuple[str, ...] = ("breakfast", "lunch", "snack", "dinner")
    max_recipe_length: int = 1500
    # ASSUMPTION: the whole menu must be built within this time; meals not ready by then are filled
    # with our own dishes. One slow LLM call can no longer keep the user waiting for minutes.
    build_timeout_s: float = 120.0
    # ASSUMPTION: foods that nearly every kitchen has. They are always allowed in a menu even if
    # the user did not list them, and in the shopping list they appear as "check what you have".
    staple_codes: tuple[str, ...] = ("sunflower_oil", "olive_oil", "butter", "sugar", "honey")
    # ASSUMPTION: protects the paid LLM from button spamming: one build per user at a time and a
    # pause after each build.
    cooldown_s: float = 30.0


class ParserConfig(BaseModel):
    """Limits for reading free-text food lists (used by ``services.food_parser``)."""

    max_text_length: int = 600  # longer messages are cut before parsing
    max_chunks: int = 30  # at most this many comma-separated items per message
    fuzzy_cutoff: float = 86.0  # 0..100: how similar a misspelled word must be to an alias
    default_quantity: float = 1.0  # "pizza" means one household measure of pizza


class BalanceConfig(BaseModel):
    """Thresholds for the "what is missing" hints (used by ``core.balance``)."""

    # WHO healthy diet guidance for adults: at least 400 g of vegetables and fruits and at least
    # 25 g of naturally occurring dietary fibre per day (potatoes and other starches not counted).
    veg_fruit_min_g: float = 400.0
    fiber_min_g: float = 25.0
    # ASSUMPTION: a menu below 2000 kcal gets a proportionally lower fibre bar (25 g would be
    # unrealistic on 1200 kcal); at or above the reference energy the full WHO value applies.
    fiber_reference_kcal: float = 2000.0
    # ASSUMPTION (approved in Stage 4.6): about 20 g of protein in each main meal.
    protein_min_per_meal_g: float = 20.0
    # Snacks are exempt from the per-meal protein rule (stored as MealType values).
    protein_checked_meals: tuple[str, ...] = ("breakfast", "lunch", "dinner")
    # ASSUMPTION: the whole day is "low in protein" below 80 % of the protein target.
    protein_day_min_share: float = 0.80
    # Pantry check on the products the user listed: a food counts as a fibre source from this
    # many grams of fibre per 100 g (ASSUMPTION).
    fiber_source_min_per_100g: float = 3.0
    protein_source_categories: tuple[str, ...] = ("meat", "fish", "egg", "dairy", "legume")
    veg_fruit_categories: tuple[str, ...] = ("vegetable", "fruit")


class ShoppingConfig(BaseModel):
    """Constants for the shopping list (used by ``core.shopping``)."""

    quantity_step: float = 0.5  # amounts to buy are rounded UP to this many household measures
    # ... except whole-piece measures (eggs, tomatoes, ...), which are rounded up to whole pieces.
    whole_measures: tuple[str, ...] = WHOLE_PIECE_MEASURES
    # Order of sections in the list (FoodCategory values); unlisted categories go last.
    category_order: tuple[str, ...] = (
        "vegetable",
        "fruit",
        "meat",
        "fish",
        "egg",
        "dairy",
        "grain",
        "starch",
        "legume",
        "bread",
        "nut",
        "fat",
        "sauce",
        "sweet",
        "other",
    )


class PresetConfig(BaseModel):
    """Placeholder for future presets (Cutting, Mass, Lazy, Budget, Family).

    Only the base preset is implemented in the MVP.
    """

    name: str = "base"
    meals_per_day: int = 4
    max_recipe_difficulty: int = 2
    price_limit: float | None = None


class Settings(BaseSettings):
    """Environment-driven settings (read from ``.env``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr = SecretStr("")
    llm_api_key: SecretStr = SecretStr("")
    # Any OpenAI-compatible chat API. The model id and the base URL differ between providers
    # (see .env.example), so there is deliberately no default base URL.
    llm_base_url: str = ""
    llm_model: str = "qwen3.8-flash"
    llm_extra_body: dict[str, Any] = Field(default_factory=dict)  # provider knobs, JSON in .env
    llm_max_tokens: int = 8000  # reasoning tokens count towards this limit on most providers
    llm_timeout_s: float = 90.0
    database_url: str = "sqlite+aiosqlite:///./nutrition_bot.db"
    log_level: str = "INFO"

    norms: NormsConfig = Field(default_factory=NormsConfig)
    slip: SlipConfig = Field(default_factory=SlipConfig)
    menu: MenuConfig = Field(default_factory=MenuConfig)
    balance: BalanceConfig = Field(default_factory=BalanceConfig)
    shopping: ShoppingConfig = Field(default_factory=ShoppingConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    preset: PresetConfig = Field(default_factory=PresetConfig)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
