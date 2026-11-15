"""Domain exceptions. Handlers translate them into friendly Russian texts."""


class NutritionError(Exception):
    """Base class for all domain errors."""


class InvalidProfileError(NutritionError):
    """Profile data is missing, non-numeric or outside realistic limits."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class UnderageError(InvalidProfileError):
    """The user is younger than the minimum supported age."""


class UnrealisticGoalError(NutritionError):
    """The requested weight change is faster than a safe plan can deliver.

    ``min_safe_weeks`` is the shortest safe duration, or ``None`` when no safe plan exists
    in this direction for the user (for example a very small user who cannot lose weight).
    """

    def __init__(
        self,
        requested_weekly_kg: float,
        safe_weekly_kg: float,
        min_safe_weeks: int | None,
    ) -> None:
        super().__init__(
            f"requested pace {requested_weekly_kg:.2f} kg/week exceeds the safe "
            f"{safe_weekly_kg:.2f} kg/week"
        )
        self.requested_weekly_kg = requested_weekly_kg
        self.safe_weekly_kg = safe_weekly_kg
        self.min_safe_weeks = min_safe_weeks


class UnknownFoodError(NutritionError):
    """A food id is not present in the catalog."""

    def __init__(self, food_id: int) -> None:
        super().__init__(f"unknown food id: {food_id}")
        self.food_id = food_id


class UnknownMeasureError(NutritionError):
    """A measure id is not present in the catalog or does not belong to the given food."""

    def __init__(self, measure_id: int, food_id: int | None = None) -> None:
        suffix = "" if food_id is None else f" for food {food_id}"
        super().__init__(f"unknown measure id: {measure_id}{suffix}")
        self.measure_id = measure_id
        self.food_id = food_id


class InvalidQuantityError(NutritionError):
    """A quantity of measures or grams is negative or not a finite number."""

    def __init__(self, quantity: float) -> None:
        super().__init__(f"quantity must be a finite number >= 0, got {quantity!r}")
        self.quantity = quantity


class InconsistentFoodError(NutritionError):
    """Catalog data is broken: for example a cooked food without a valid raw counterpart."""

    def __init__(self, food_id: int, reason: str) -> None:
        super().__init__(f"food {food_id}: {reason}")
        self.food_id = food_id
        self.reason = reason


class LLMError(NutritionError):
    """The language model could not be reached or returned nothing usable (transport level)."""


class InvalidLLMResponseError(NutritionError):
    """The model answered, but the answer failed validation. ``problems`` explain why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class InvalidMenuRequestError(NutritionError):
    """The requested set of meals makes no sense (empty, duplicated or unknown meal type)."""


class MenuUnavailableError(NutritionError):
    """Not even a fallback dish could be fitted to the target (should not happen with real data)."""

    def __init__(self, meal_type: str) -> None:
        super().__init__(f"no dish could be built for {meal_type}")
        self.meal_type = meal_type
