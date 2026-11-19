"""FSM state groups (the steps of each conversation)."""

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """Questions asked after /start."""

    consent = State()
    sex = State()
    age = State()
    height = State()
    weight = State()
    activity = State()
    goal = State()


class MenuFlow(StatesGroup):
    """/menu: number of days, then the products the user has, then clarifying questions."""

    days = State()
    products = State()
    clarify = State()


class SlipFlow(StatesGroup):
    """/slip: what was eaten, clarifying questions, confirmation."""

    text = State()
    clarify = State()
    confirm = State()


class GoalCheck(StatesGroup):
    """The optional "target weight and term" check."""

    target = State()
    weeks = State()
