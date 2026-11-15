"""Daily calorie and macro norms (Mifflin-St Jeor). Deterministic, no I/O."""

import math

from nutrition_bot.config import NormsConfig
from nutrition_bot.core.errors import InvalidProfileError, UnderageError, UnrealisticGoalError
from nutrition_bot.core.models import DailyNorm, Goal, Nutrients, Profile, Sex


def _check_range(field: str, value: float, low: float, high: float) -> None:
    """Raise ``InvalidProfileError`` if ``value`` is not a finite number within bounds."""
    if not math.isfinite(value) or not low <= value <= high:
        raise InvalidProfileError(field, f"{field} must be between {low:g} and {high:g}")


def validate_profile(profile: Profile, cfg: NormsConfig) -> None:
    """Reject unrealistic or unsupported input (minors, impossible height or weight)."""
    if profile.age < cfg.min_age:
        raise UnderageError("age", f"age must be at least {cfg.min_age}")
    if profile.age > cfg.max_age:
        raise InvalidProfileError("age", f"age must be at most {cfg.max_age}")
    _check_range("height_cm", profile.height_cm, cfg.min_height_cm, cfg.max_height_cm)
    _check_range("weight_kg", profile.weight_kg, cfg.min_weight_kg, cfg.max_weight_kg)
    if profile.activity.value not in cfg.activity_factors:
        raise InvalidProfileError("activity", f"unknown activity level: {profile.activity.value}")
    if profile.goal.value not in cfg.protein_g_per_kg:
        raise InvalidProfileError("goal", f"unknown goal: {profile.goal.value}")


def calc_bmr(profile: Profile, cfg: NormsConfig) -> float:
    """Basal metabolic rate in kcal/day by the Mifflin-St Jeor equation."""
    offset = cfg.bmr_male_offset if profile.sex is Sex.MALE else cfg.bmr_female_offset
    return (
        cfg.bmr_weight_coef * profile.weight_kg
        + cfg.bmr_height_coef * profile.height_cm
        - cfg.bmr_age_coef * profile.age
        + offset
    )


def calc_tdee(bmr: float, profile: Profile, cfg: NormsConfig) -> float:
    """Total daily energy expenditure: BMR times the activity factor."""
    return bmr * cfg.activity_factors[profile.activity.value]


def calc_floor_kcal(sex: Sex, bmr: float, cfg: NormsConfig) -> float:
    """Absolute lower bound of daily kcal: the sex-based minimum, but never below BMR."""
    sex_floor = cfg.min_kcal_male if sex is Sex.MALE else cfg.min_kcal_female
    return max(sex_floor, bmr)


def calc_target_kcal(goal: Goal, tdee: float, floor_kcal: float, cfg: NormsConfig) -> float:
    """Daily kcal target for the goal.

    For "lose" the deficit is capped by ``max_deficit`` and by the floor. The result never
    exceeds maintenance: if the floor is above TDEE (very small, elderly users) the user
    simply gets TDEE instead of an accidental surplus.
    """
    match goal:
        case Goal.MAINTAIN:
            return tdee
        case Goal.GAIN:
            return tdee * (1 + cfg.gain_surplus)
        case Goal.LOSE:
            deficit = min(cfg.lose_deficit, cfg.max_deficit)
            return min(tdee, max(tdee * (1 - deficit), floor_kcal))


def calc_macros(goal: Goal, weight_kg: float, kcal: float, cfg: NormsConfig) -> Nutrients:
    """Split ``kcal`` into protein, fat and carbs.

    Protein is set per kg of body weight (capped by a share of kcal), fat is a share of kcal,
    carbs take the rest. Energy always adds up to ``kcal``.
    """
    protein_g = min(
        cfg.protein_g_per_kg[goal.value] * weight_kg,
        cfg.max_protein_share * kcal / cfg.kcal_per_g_protein,
    )
    fat_g = cfg.fat_share * kcal / cfg.kcal_per_g_fat
    carb_kcal = kcal - protein_g * cfg.kcal_per_g_protein - fat_g * cfg.kcal_per_g_fat
    return Nutrients(
        kcal=kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carb_g=carb_kcal / cfg.kcal_per_g_carb,
    )


def calculate_daily_norm(profile: Profile, cfg: NormsConfig) -> DailyNorm:
    """Validate the profile and compute BMR, TDEE, the kcal floor and the daily target."""
    validate_profile(profile, cfg)
    bmr = calc_bmr(profile, cfg)
    tdee = calc_tdee(bmr, profile, cfg)
    floor_kcal = calc_floor_kcal(profile.sex, bmr, cfg)
    kcal = calc_target_kcal(profile.goal, tdee, floor_kcal, cfg)
    return DailyNorm(
        bmr=bmr,
        tdee=tdee,
        floor_kcal=floor_kcal,
        target=calc_macros(profile.goal, profile.weight_kg, kcal, cfg),
    )


def max_safe_weekly_change_kg(profile: Profile, cfg: NormsConfig) -> float:
    """Fastest safe body-mass change per week (kg, >= 0) that the plan can deliver.

    Uses the maximum allowed deficit (lose) or surplus (gain), including the kcal floor.
    Returns 0 for the "maintain" goal and when the floor leaves no room for a deficit.
    """
    bmr = calc_bmr(profile, cfg)
    tdee = calc_tdee(bmr, profile, cfg)
    floor_kcal = calc_floor_kcal(profile.sex, bmr, cfg)
    match profile.goal:
        case Goal.MAINTAIN:
            daily_gap = 0.0
        case Goal.GAIN:
            daily_gap = tdee * cfg.gain_surplus
        case Goal.LOSE:
            daily_gap = tdee - min(tdee, max(tdee * (1 - cfg.max_deficit), floor_kcal))
    return daily_gap * 7 / cfg.kcal_per_kg_body_change


def check_weight_goal(
    profile: Profile, target_weight_kg: float, weeks: int, cfg: NormsConfig
) -> float:
    """Check that reaching ``target_weight_kg`` in ``weeks`` is safe; return kg per week.

    Raises ``InvalidProfileError`` for inconsistent input (wrong direction for the goal,
    out-of-range weight or duration) and ``UnrealisticGoalError`` when the pace is too fast.
    """
    validate_profile(profile, cfg)
    _check_range("target_weight_kg", target_weight_kg, cfg.min_weight_kg, cfg.max_weight_kg)
    if not 1 <= weeks <= cfg.max_goal_weeks:
        raise InvalidProfileError("weeks", f"weeks must be between 1 and {cfg.max_goal_weeks}")
    delta = target_weight_kg - profile.weight_kg
    if profile.goal is Goal.MAINTAIN:
        raise InvalidProfileError("goal", "a target weight is not used with the maintain goal")
    if (profile.goal is Goal.LOSE and delta >= 0) or (profile.goal is Goal.GAIN and delta <= 0):
        raise InvalidProfileError("target_weight_kg", "target weight contradicts the goal")

    requested = abs(delta) / weeks
    safe = max_safe_weekly_change_kg(profile, cfg)
    if requested > safe + 1e-9:
        min_weeks = math.ceil(abs(delta) / safe - 1e-9) if safe > 0 else None
        raise UnrealisticGoalError(requested, safe, min_weeks)
    return requested


def is_below_sex_minimum(sex: Sex, kcal: float, cfg: NormsConfig) -> bool:
    """Is a daily target under the absolute minimum for the sex (1200/1500 kcal by default)?

    This happens for very small or elderly users, whose maintenance energy is itself below the
    minimum. The bot never plans below the computed value, but should suggest a doctor.
    """
    minimum = cfg.min_kcal_male if sex is Sex.MALE else cfg.min_kcal_female
    return kcal < minimum - 1e-9
