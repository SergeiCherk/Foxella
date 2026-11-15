"""Tests for core.norms. Reference numbers were computed by hand from the Mifflin-St Jeor formula.

Male   30 y, 180 cm, 80 kg: BMR = 10*80 + 6.25*180 - 5*30 + 5    = 1780.0
Female 25 y, 165 cm, 60 kg: BMR = 10*60 + 6.25*165 - 5*25 - 161  = 1345.25
"""

import dataclasses
import itertools
import math

import pytest

from nutrition_bot.config import NormsConfig
from nutrition_bot.core.errors import (
    InvalidProfileError,
    NutritionError,
    UnderageError,
    UnrealisticGoalError,
)
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.core.norms import (
    calc_bmr,
    calc_floor_kcal,
    calc_macros,
    calc_target_kcal,
    calc_tdee,
    calculate_daily_norm,
    check_weight_goal,
    max_safe_weekly_change_kg,
    validate_profile,
)

CFG = NormsConfig()

MALE = Profile(Sex.MALE, 30, 180.0, 80.0, ActivityLevel.MODERATE, Goal.MAINTAIN)
FEMALE = Profile(Sex.FEMALE, 25, 165.0, 60.0, ActivityLevel.LIGHT, Goal.MAINTAIN)


def make(**changes: object) -> Profile:
    """Copy of the reference male profile with some fields changed."""
    return dataclasses.replace(MALE, **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------- BMR / TDEE


@pytest.mark.parametrize(
    ("profile", "expected"),
    [(MALE, 1780.0), (FEMALE, 1345.25)],
    ids=["male", "female"],
)
def test_bmr_reference_values(profile: Profile, expected: float) -> None:
    assert calc_bmr(profile, CFG) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("activity", "male_tdee", "female_tdee"),
    [
        (ActivityLevel.SEDENTARY, 2136.0, 1614.3),
        (ActivityLevel.LIGHT, 2447.5, 1849.71875),
        (ActivityLevel.MODERATE, 2759.0, 2085.1375),
        (ActivityLevel.HIGH, 3070.5, 2320.55625),
        (ActivityLevel.VERY_HIGH, 3382.0, 2555.975),
    ],
)
def test_tdee_for_every_activity_level(
    activity: ActivityLevel, male_tdee: float, female_tdee: float
) -> None:
    male = dataclasses.replace(MALE, activity=activity)
    female = dataclasses.replace(FEMALE, activity=activity)
    assert calc_tdee(1780.0, male, CFG) == pytest.approx(male_tdee)
    assert calc_tdee(1345.25, female, CFG) == pytest.approx(female_tdee)


# -------------------------------------------------------------- goals / kcal


@pytest.mark.parametrize(
    ("goal", "expected_kcal"),
    [
        (Goal.MAINTAIN, 2759.0),
        (Goal.LOSE, 2759.0 * 0.85),  # default 15 % deficit
        (Goal.GAIN, 2759.0 * 1.10),  # 10 % surplus
    ],
)
def test_target_kcal_for_every_goal(goal: Goal, expected_kcal: float) -> None:
    norm = calculate_daily_norm(make(goal=goal), CFG)
    assert norm.bmr == pytest.approx(1780.0)
    assert norm.tdee == pytest.approx(2759.0)
    assert norm.target.kcal == pytest.approx(expected_kcal)


def test_deficit_is_capped_at_max_deficit() -> None:
    greedy = NormsConfig(lose_deficit=0.5, max_deficit=0.20)
    norm = calculate_daily_norm(make(goal=Goal.LOSE), greedy)
    assert norm.target.kcal == pytest.approx(2759.0 * 0.80)


# ------------------------------------------------------------- kcal floor


def test_floor_is_bmr_when_bmr_is_above_the_sex_minimum() -> None:
    assert calc_floor_kcal(Sex.MALE, 1780.0, CFG) == pytest.approx(1780.0)


def test_floor_is_sex_minimum_when_bmr_is_lower() -> None:
    assert calc_floor_kcal(Sex.FEMALE, 1114.0, CFG) == pytest.approx(1200.0)
    assert calc_floor_kcal(Sex.MALE, 1286.25, CFG) == pytest.approx(1500.0)


def test_lose_goal_never_goes_below_female_floor() -> None:
    # BMR 1114, TDEE 1336.8, 15 % deficit would be 1136.28 -> lifted to the 1200 floor.
    profile = Profile(Sex.FEMALE, 45, 160.0, 50.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    norm = calculate_daily_norm(profile, CFG)
    assert norm.floor_kcal == pytest.approx(1200.0)
    assert norm.target.kcal == pytest.approx(1200.0)


def test_lose_goal_never_goes_below_male_floor() -> None:
    # BMR 1286.25, TDEE 1543.5, 15 % deficit would be 1311.98 -> lifted to the 1500 floor.
    profile = Profile(Sex.MALE, 60, 165.0, 55.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    norm = calculate_daily_norm(profile, CFG)
    assert norm.floor_kcal == pytest.approx(1500.0)
    assert norm.target.kcal == pytest.approx(1500.0)


def test_floor_above_tdee_never_produces_a_surplus_for_lose() -> None:
    # BMR 826.5, TDEE 991.8: the 1200 floor is above maintenance -> plain maintenance.
    profile = Profile(Sex.FEMALE, 80, 150.0, 45.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    norm = calculate_daily_norm(profile, CFG)
    assert norm.tdee == pytest.approx(991.8)
    assert norm.target.kcal == pytest.approx(991.8)


def test_calc_target_kcal_direct() -> None:
    assert calc_target_kcal(Goal.LOSE, 2000.0, 1200.0, CFG) == pytest.approx(1700.0)
    assert calc_target_kcal(Goal.MAINTAIN, 2000.0, 1200.0, CFG) == pytest.approx(2000.0)
    assert calc_target_kcal(Goal.GAIN, 2000.0, 1200.0, CFG) == pytest.approx(2200.0)


# ----------------------------------------------------------------- macros


def test_macros_for_lose_goal() -> None:
    kcal = 2759.0 * 0.85
    norm = calculate_daily_norm(make(goal=Goal.LOSE), CFG)
    assert norm.target.protein_g == pytest.approx(1.8 * 80.0)
    assert norm.target.fat_g == pytest.approx(0.28 * kcal / 9.0)
    expected_carbs = (kcal - 4.0 * 144.0 - 0.28 * kcal) / 4.0
    assert norm.target.carb_g == pytest.approx(expected_carbs)


@pytest.mark.parametrize(
    ("goal", "protein_per_kg"),
    [(Goal.LOSE, 1.8), (Goal.MAINTAIN, 1.4), (Goal.GAIN, 1.6)],
)
def test_protein_per_kg_by_goal(goal: Goal, protein_per_kg: float) -> None:
    norm = calculate_daily_norm(make(goal=goal), CFG)
    assert norm.target.protein_g == pytest.approx(protein_per_kg * 80.0)


def test_protein_is_capped_by_share_of_calories_for_heavy_users() -> None:
    # 120 kg * 1.8 = 216 g would be too much for ~1908 kcal; cap = 0.30 * kcal / 4.
    profile = Profile(Sex.FEMALE, 40, 165.0, 120.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    norm = calculate_daily_norm(profile, CFG)
    assert norm.target.kcal == pytest.approx(1870.25 * 1.2 * 0.85)
    assert norm.target.protein_g == pytest.approx(0.30 * norm.target.kcal / 4.0)
    assert norm.target.carb_g > 0


def test_calc_macros_direct() -> None:
    macros = calc_macros(Goal.MAINTAIN, 70.0, 2000.0, CFG)
    assert macros.kcal == 2000.0
    assert macros.protein_g == pytest.approx(98.0)  # 1.4 * 70


# ---------------------------------------------------- validation (errors)


@pytest.mark.parametrize("age", [18, 19, 99, 100])
def test_supported_ages_are_accepted(age: int) -> None:
    validate_profile(make(age=age), CFG)


@pytest.mark.parametrize("age", [0, 10, 17])
def test_minors_are_rejected(age: int) -> None:
    with pytest.raises(UnderageError) as exc:
        calculate_daily_norm(make(age=age), CFG)
    assert exc.value.field == "age"
    assert isinstance(exc.value, InvalidProfileError)
    assert isinstance(exc.value, NutritionError)


@pytest.mark.parametrize("age", [101, 150])
def test_unrealistic_age_is_rejected_but_is_not_underage(age: int) -> None:
    with pytest.raises(InvalidProfileError) as exc:
        calculate_daily_norm(make(age=age), CFG)
    assert not isinstance(exc.value, UnderageError)
    assert exc.value.field == "age"


@pytest.mark.parametrize("height", [120.0, 175.5, 230.0])
def test_valid_heights(height: float) -> None:
    validate_profile(make(height_cm=height), CFG)


@pytest.mark.parametrize("height", [119.9, 0.0, -170.0, 230.1, 1800.0])
def test_unrealistic_heights_are_rejected(height: float) -> None:
    with pytest.raises(InvalidProfileError) as exc:
        calculate_daily_norm(make(height_cm=height), CFG)
    assert exc.value.field == "height_cm"


@pytest.mark.parametrize("weight", [30.0, 80.0, 300.0])
def test_valid_weights(weight: float) -> None:
    validate_profile(make(weight_kg=weight), CFG)


@pytest.mark.parametrize("weight", [29.9, 0.0, -5.0, 300.1, 8000.0])
def test_unrealistic_weights_are_rejected(weight: float) -> None:
    with pytest.raises(InvalidProfileError) as exc:
        calculate_daily_norm(make(weight_kg=weight), CFG)
    assert exc.value.field == "weight_kg"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(bad: float) -> None:
    with pytest.raises(InvalidProfileError):
        validate_profile(make(weight_kg=bad), CFG)
    with pytest.raises(InvalidProfileError):
        validate_profile(make(height_cm=bad), CFG)


def test_activity_missing_from_config_is_rejected() -> None:
    cfg = NormsConfig(activity_factors={"sedentary": 1.2})
    with pytest.raises(InvalidProfileError) as exc:
        validate_profile(make(activity=ActivityLevel.HIGH), cfg)
    assert exc.value.field == "activity"


def test_goal_missing_from_config_is_rejected() -> None:
    cfg = NormsConfig(protein_g_per_kg={"maintain": 1.4})
    with pytest.raises(InvalidProfileError) as exc:
        validate_profile(make(goal=Goal.GAIN), cfg)
    assert exc.value.field == "goal"


# ------------------------------------------------- invariants on a grid


GRID = list(
    itertools.product(
        Sex,
        [18, 30, 50, 80],
        [150.0, 180.0],
        [45.0, 70.0, 110.0],
        ActivityLevel,
        Goal,
    )
)


@pytest.mark.parametrize(("sex", "age", "height", "weight", "activity", "goal"), GRID)
def test_invariants_hold_for_many_profiles(
    sex: Sex, age: int, height: float, weight: float, activity: ActivityLevel, goal: Goal
) -> None:
    norm = calculate_daily_norm(Profile(sex, age, height, weight, activity, goal), CFG)
    t = norm.target

    # energy adds up: 4*P + 4*C + 9*F == kcal
    assert 4 * t.protein_g + 4 * t.carb_g + 9 * t.fat_g == pytest.approx(t.kcal)
    assert t.protein_g > 0
    assert t.fat_g > 0
    assert t.carb_g > 0

    if goal is Goal.MAINTAIN:
        assert t.kcal == pytest.approx(norm.tdee)
    elif goal is Goal.GAIN:
        assert t.kcal == pytest.approx(norm.tdee * 1.10)
    else:
        assert t.kcal <= norm.tdee + 1e-9  # never a surplus when losing
        assert t.kcal >= norm.tdee * 0.80 - 1e-9  # deficit never above 20 %
        # the floor is respected unless it is higher than maintenance itself
        assert t.kcal >= min(norm.floor_kcal, norm.tdee) - 1e-9


# ------------------------------------------------ weight goal pace check


# Male 30 y, 180 cm, 80 kg, moderate: TDEE 2759. Max deficit 20 % -> 551.8 kcal/day
# -> 551.8 * 7 / 7700 = 0.50164 kg/week. Max surplus 10 % -> 275.9 -> 0.25085 kg/week.


def test_max_safe_pace_for_lose_and_gain() -> None:
    assert max_safe_weekly_change_kg(make(goal=Goal.LOSE), CFG) == pytest.approx(0.50164, abs=1e-4)
    assert max_safe_weekly_change_kg(make(goal=Goal.GAIN), CFG) == pytest.approx(0.25085, abs=1e-4)
    assert max_safe_weekly_change_kg(make(goal=Goal.MAINTAIN), CFG) == 0.0


def test_ten_kg_in_one_week_is_refused_with_a_safe_alternative() -> None:
    with pytest.raises(UnrealisticGoalError) as exc:
        check_weight_goal(make(goal=Goal.LOSE), 70.0, 1, CFG)
    assert exc.value.requested_weekly_kg == pytest.approx(10.0)
    assert exc.value.safe_weekly_kg == pytest.approx(0.50164, abs=1e-4)
    assert exc.value.min_safe_weeks == 20  # 10 / 0.50164 = 19.93 -> 20


def test_safe_loss_returns_weekly_pace() -> None:
    assert check_weight_goal(make(goal=Goal.LOSE), 70.0, 20, CFG) == pytest.approx(0.5)


def test_gain_pace_is_checked_against_the_surplus() -> None:
    assert check_weight_goal(make(goal=Goal.GAIN), 85.0, 20, CFG) == pytest.approx(0.25)
    with pytest.raises(UnrealisticGoalError) as exc:
        check_weight_goal(make(goal=Goal.GAIN), 85.0, 19, CFG)
    assert exc.value.min_safe_weeks == 20


def test_no_safe_loss_when_floor_leaves_no_deficit() -> None:
    # TDEE 991.8 is below the 1200 floor: there is no room for a deficit at all.
    tiny = Profile(Sex.FEMALE, 80, 150.0, 45.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    with pytest.raises(UnrealisticGoalError) as exc:
        check_weight_goal(tiny, 44.0, 52, CFG)
    assert exc.value.safe_weekly_kg == 0.0
    assert exc.value.min_safe_weeks is None


@pytest.mark.parametrize(
    ("goal", "target", "weeks", "field"),
    [
        (Goal.LOSE, 85.0, 10, "target_weight_kg"),  # heavier than now, but goal is lose
        (Goal.LOSE, 80.0, 10, "target_weight_kg"),  # same weight
        (Goal.GAIN, 75.0, 10, "target_weight_kg"),  # lighter than now, but goal is gain
        (Goal.MAINTAIN, 80.0, 10, "goal"),
        (Goal.LOSE, 20.0, 10, "target_weight_kg"),  # outside realistic range
        (Goal.LOSE, 70.0, 0, "weeks"),
        (Goal.LOSE, 70.0, 105, "weeks"),
    ],
)
def test_inconsistent_goal_input_is_rejected(
    goal: Goal, target: float, weeks: int, field: str
) -> None:
    with pytest.raises(InvalidProfileError) as exc:
        check_weight_goal(make(goal=goal), target, weeks, CFG)
    assert exc.value.field == field


# ------------------------------------------------ minimum kcal for the sex


@pytest.mark.parametrize(
    ("sex", "kcal", "below"),
    [
        (Sex.FEMALE, 1199.9, True),
        (Sex.FEMALE, 1200.0, False),
        (Sex.FEMALE, 1500.0, False),
        (Sex.MALE, 1499.9, True),
        (Sex.MALE, 1500.0, False),
        (Sex.MALE, 1200.0, True),  # fine for a woman, below the minimum for a man
        (Sex.FEMALE, 991.8, True),
    ],
)
def test_is_below_sex_minimum(sex: Sex, kcal: float, below: bool) -> None:
    from nutrition_bot.core.norms import is_below_sex_minimum

    assert is_below_sex_minimum(sex, kcal, CFG) is below


def test_a_very_small_elderly_user_is_below_the_minimum_a_typical_one_is_not() -> None:
    from nutrition_bot.core.norms import is_below_sex_minimum

    tiny = Profile(Sex.FEMALE, 80, 150.0, 45.0, ActivityLevel.SEDENTARY, Goal.LOSE)
    assert is_below_sex_minimum(Sex.FEMALE, calculate_daily_norm(tiny, CFG).target.kcal, CFG)
    typical = Profile(Sex.FEMALE, 32, 168.0, 64.5, ActivityLevel.LIGHT, Goal.LOSE)
    assert not is_below_sex_minimum(Sex.FEMALE, calculate_daily_norm(typical, CFG).target.kcal, CFG)
