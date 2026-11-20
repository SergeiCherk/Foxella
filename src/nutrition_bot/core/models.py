"""Domain types shared by the pure business logic."""

from dataclasses import dataclass
from enum import StrEnum


class Sex(StrEnum):
    """Biological sex used by the Mifflin-St Jeor formula."""

    MALE = "male"
    FEMALE = "female"


class ActivityLevel(StrEnum):
    """Physical activity level; values are keys of ``NormsConfig.activity_factors``."""

    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class Goal(StrEnum):
    """User goal; values are keys of ``NormsConfig.protein_g_per_kg``."""

    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"


@dataclass(frozen=True, slots=True)
class Profile:
    """Data entered by the user during onboarding."""

    sex: Sex
    age: int
    height_cm: float
    weight_kg: float
    activity: ActivityLevel
    goal: Goal


@dataclass(frozen=True, slots=True)
class Nutrients:
    """Energy and macronutrients. Kept unrounded; round only when showing to the user."""

    kcal: float
    protein_g: float
    fat_g: float
    carb_g: float
    fiber_g: float = 0.0


@dataclass(frozen=True, slots=True)
class DailyNorm:
    """Result of the norm calculation for one user."""

    bmr: float
    tdee: float
    floor_kcal: float  # the plan must never go below this (see core.slip)
    target: Nutrients


class FoodState(StrEnum):
    """Physical state the nutrients of a food refer to."""

    RAW = "raw"  # uncooked (dry rice, raw chicken)
    COOKED = "cooked"  # after cooking; always linked to a raw food by ``yield_factor``
    READY = "ready"  # eaten as is (fruit, bread, yogurt)


class FoodCategory(StrEnum):
    """Food group, used for "what is missing in the diet" hints."""

    GRAIN = "grain"
    STARCH = "starch"  # potatoes and similar: not counted as vegetables
    MEAT = "meat"
    FISH = "fish"
    EGG = "egg"
    DAIRY = "dairy"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    LEGUME = "legume"
    NUT = "nut"
    FAT = "fat"
    BREAD = "bread"
    SWEET = "sweet"
    SAUCE = "sauce"
    DISH = "dish"  # a ready dish (borscht, pizza): for "I ate", never in menus
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Food:
    """A product with nutrients per 100 g in its own state (raw and cooked are separate foods)."""

    id: int
    code: str
    name_ru: str
    state: FoodState
    category: FoodCategory
    per_100g: Nutrients
    raw_food_id: int | None = None  # for COOKED foods: the raw food it comes from
    yield_factor: float | None = None  # for COOKED foods: cooked grams per 1 g of raw


@dataclass(frozen=True, slots=True)
class Measure:
    """A household measure ("ladle", "breast", "tablespoon") of one food, in grams."""

    id: int
    food_id: int
    name_ru: str
    grams: float


class MealType(StrEnum):
    """Kind of eating occasion within a day."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


@dataclass(frozen=True, slots=True)
class DishItem:
    """One ingredient of a dish: ``quantity`` household measures of a food."""

    food_id: int
    measure_id: int
    quantity: float


@dataclass(frozen=True, slots=True)
class Dish:
    """A dish made of ingredients. Nutrients are always computed from the items, never stored."""

    name: str
    items: tuple[DishItem, ...]
    recipe_text: str = ""


@dataclass(frozen=True, slots=True)
class Meal:
    """Dishes eaten together at one occasion (for example, lunch)."""

    meal_type: MealType
    dishes: tuple[Dish, ...]
