"""API / storage models (camelCase, matching the frontend)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

GoalStatus = Literal["backlog", "todo", "doing", "done"]
Priority = Literal["high", "medium", "low"]
OptionKind = Literal["yes", "yes_and", "no", "no_and", "route"]
ChapterSource = Literal["calendar", "goal", "custom", "meal", "break"]


# ---------- Goals (the Trello-style board) ----------


class GoalIn(BaseModel):
    title: str
    description: str = ""
    status: GoalStatus = "todo"
    priority: Priority = "medium"
    estimateMinutes: int | None = None
    dueDate: str | None = None  # YYYY-MM-DD
    tags: list[str] = Field(default_factory=list)
    order: float = 0


class GoalPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    status: GoalStatus | None = None
    priority: Priority | None = None
    estimateMinutes: int | None = None
    dueDate: str | None = None
    tags: list[str] | None = None
    order: float | None = None


class Goal(GoalIn):
    id: str
    createdAt: str | None = None
    updatedAt: str | None = None


# ---------- Day plans (the adventure) ----------


class Option(BaseModel):
    id: str
    kind: OptionKind = "route"
    storylineId: str | None = None
    title: str
    detail: str = ""
    durationMinutes: int | None = None
    goalIds: list[str] = Field(default_factory=list)
    # Where the day goes after this choice: another timeline's id, or None to stay put.
    nextTimelineId: str | None = None


class Chapter(BaseModel):
    id: str
    start: str  # HH:MM local time
    end: str  # HH:MM local time
    title: str
    priority: Priority = "medium"
    source: ChapterSource = "custom"
    calendarEventId: str | None = None  # "<calendarKey>:<eventId>" for calendar chapters
    calendarId: str | None = None  # which linked calendar the source event is on
    calendarName: str | None = None
    calendarColor: str | None = None
    options: list[Option] = Field(default_factory=list)
    chosenOptionId: str | None = None
    chosenAt: str | None = None
    scheduledEventId: str | None = None
    scheduledCalendarId: str | None = None  # where CYOA put the chosen path
    missed: bool = False  # the person says (or we assume) this one didn't happen
    timelineId: str | None = None  # which version of the day this chapter belongs to
    # The same activity on different timelines shares an activityId (e.g. "event:<id>",
    # "meal:lunch", "chem-study"), so doing it on one timeline counts on all of them.
    activityId: str | None = None


class Timeline(BaseModel):
    """One complete version of the day: the same activities, arranged differently."""

    id: str
    name: str
    description: str = ""
    color: str | None = None
    # healthy = perfect healthy routine, recovery = catch-up / recovery, rebel = just being human
    role: Literal["healthy", "recovery", "rebel"] | None = None
    # Calendar events this version of the day keeps (calendarEventIds). The first timeline
    # always keeps every event; the others each skip some to do something else instead.
    keptEventIds: list[str] = Field(default_factory=list)
    skippedEvents: list[str] = Field(default_factory=list)  # titles, for display


class Storyline(BaseModel):
    id: str
    name: str
    description: str = ""
    color: str | None = None


class DayPlan(BaseModel):
    date: str  # YYYY-MM-DD
    priorities: str = ""
    dayStart: str = "08:00"
    dayEnd: str = "22:00"
    summary: str = ""
    storylines: list[Storyline] = Field(default_factory=list)
    # Empty for single-track plans (older ones). Chapters of every timeline live in
    # `chapters`, each tagged with its timelineId.
    timelines: list[Timeline] = Field(default_factory=list)
    currentTimelineId: str | None = None  # where the person is right now
    chapters: list[Chapter] = Field(default_factory=list)
    revisions: list["Revision"] = Field(default_factory=list)  # feedback conversation with the AI
    updatedAt: str | None = None


class Revision(BaseModel):
    at: str
    feedback: str
    timelineId: str | None = None  # None = all timelines
    reply: str = ""
    applied: int = 0


class ReviseIn(BaseModel):
    date: str
    feedback: str = Field(min_length=1, max_length=1000)
    timelineId: str | None = None  # revise just this timeline (None = all)
    rewrite: bool = False  # rewrite the chosen timeline from scratch (same role)


class MissedIn(BaseModel):
    missed: bool = True


class ChooseIn(BaseModel):
    optionId: str
    addToCalendar: bool = True


# ---------- User settings ----------


class UserSettings(BaseModel):
    email: str = ""
    displayName: str = ""
    timezone: str = "UTC"
    reminderLeadMinutes: int = 5
    emailReminders: bool = True
    notifyEmail: str = ""
    # Display only - the authoritative linked calendar lives in users/{uid}/private/calendar
    calendarId: str = ""
    calendarName: str = ""
    googleConnected: bool = False
    hasWritableCalendar: bool = False
    # Meals the planner must fit in (each still offers a choice of how to eat)
    breakfastEnabled: bool = True
    breakfastTime: str = "08:00"
    lunchEnabled: bool = True
    lunchTime: str = "12:30"
    dinnerEnabled: bool = True
    dinnerTime: str = "18:30"
    mealNotes: str = ""  # e.g. "vegetarian, usually cook dinner at home"
    assumeMissed: bool = True  # chapters whose time passed without a choice count as missed
    sleepTargetHours: float = 8.0
    # Patience economy: % per hour the balance grows by while it's negative (compounding).
    patienceInterestPerHour: float = 1.0
    # Default patience per board tag (set on the Board; replaced whole via /api/patience/tags).
    patienceTags: dict[str, "TagPatience"] = Field(default_factory=dict)


class UserSettingsPatch(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    sleepTargetHours: float | None = Field(default=None, ge=4, le=12)
    reminderLeadMinutes: int | None = Field(default=None, ge=0, le=240)
    emailReminders: bool | None = None
    # Reminders may only go to the user's own verified sign-in email (checked in the route),
    # so CYOA can't be used to send mail to other people's inboxes.
    notifyEmail: str | None = Field(default=None, max_length=254)
    breakfastEnabled: bool | None = None
    breakfastTime: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    lunchEnabled: bool | None = None
    lunchTime: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    dinnerEnabled: bool | None = None
    dinnerTime: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    mealNotes: str | None = Field(default=None, max_length=300)
    assumeMissed: bool | None = None
    patienceInterestPerHour: float | None = Field(default=None, ge=0, le=25)
    # No calendarId here on purpose: it can only be set via /api/calendar/link (ownership-checked).


# ---------- Sleep ----------

SleepStatus = Literal["unknown", "rested", "low", "deprived"]


class SleepSession(BaseModel):
    id: str
    start: str  # UTC ISO
    end: str | None = None  # UTC ISO; None while asleep
    source: Literal["live", "manual"] = "live"


class SleepAt(BaseModel):
    at: str | None = None  # ISO with offset; None = now


class SleepLogIn(BaseModel):
    start: str
    end: str


class SleepSummary(BaseModel):
    asleep: bool
    sleepingSince: str | None
    sessionId: str | None
    targetHours: float
    status: SleepStatus
    lastSleepHours: float | None
    lastWokeAt: str | None
    hoursAwake: float | None
    sleptLast24h: float
    avgHours7d: float | None
    debtHours: float
    nightsTracked: int
    typicalBedtime: str | None  # HH:MM local
    typicalWake: str | None
    wakeAnchor: str  # the wake-up time the bedtime suggestion is based on
    suggestedBedtime: str
    windDownAt: str
    sessions: list[SleepSession]


# ---------- AI requests ----------


class PlanDayIn(BaseModel):
    date: str
    priorities: str = ""
    dayStart: str = "08:00"
    dayEnd: str = "22:00"
    useCalendar: bool = True
    goalIds: list[str] | None = None  # None = use all open goals
    routes: int = 3  # how many storylines to aim for (2-4)
    timelines: int = Field(default=3, ge=2, le=3)  # versions of the day: healthy, recovery, (rebel)


class ChapterOptionsIn(BaseModel):
    date: str
    chapterId: str
    hint: str = ""


# ---------- AI memory ----------


class MemoryNote(BaseModel):
    id: str
    text: str
    source: Literal["user", "ai"] = "ai"
    createdAt: str | None = None


class MemoryLogEntry(BaseModel):
    at: str
    type: str
    date: str | None = None
    text: str


class AIMemory(BaseModel):
    notes: list[MemoryNote] = Field(default_factory=list)
    log: list[MemoryLogEntry] = Field(default_factory=list)


class MemoryNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=280)


# ---------- Hope: manifestations ----------

# "goal" = an ultimate goal in life (older entries were "positive" manifestations).
ManifestationKind = Literal["complicated", "goal"]

NaturalList = list[Annotated[str, Field(min_length=1, max_length=300)]]


class ManifestationIn(BaseModel):
    kind: ManifestationKind
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)  # goal only
    # goal only: progress already made, or what makes them grateful for where they are
    evidence: NaturalList = Field(default_factory=list, max_length=30)
    # complicated only:
    problem: str = Field(default="", max_length=2000)  # the stressor, as unbiased as possible
    naturalManifestations: NaturalList = Field(default_factory=list, max_length=30)  # what comes with it
    corrected: str = Field(default="", max_length=600)  # the words to repeat to yourself
    goalId: str = Field(default="", max_length=64)  # the ultimate goal it leads toward


class ManifestationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    evidence: NaturalList | None = Field(default=None, max_length=30)
    problem: str | None = Field(default=None, max_length=2000)
    naturalManifestations: NaturalList | None = Field(default=None, max_length=30)
    corrected: str | None = Field(default=None, max_length=600)
    goalId: str | None = Field(default=None, max_length=64)


class Manifestation(ManifestationIn):
    id: str
    createdAt: str | None = None
    updatedAt: str | None = None


class CorrectedSuggestIn(BaseModel):
    title: str = Field(default="", max_length=120)
    problem: str = Field(min_length=1, max_length=2000)
    naturalManifestations: NaturalList = Field(default_factory=list, max_length=30)


class CorrectedSuggestions(BaseModel):
    suggestions: list[str]


# ---------- Patience: the currency of hope ----------

PatienceKind = Literal["emission", "absorption"]  # gained / lost
PatienceSource = Literal["start", "open", "revise", "sleep", "task", "log", "interest"]


class TagPatience(BaseModel):
    """A board tag's default patience.

    fixed:    every time costs (negative) or gives (positive) `points`.
    parabola: a want or need. It climbs to `points` at `idealMinutes` (the climax), then
              falls back to 0 after another `widthMinutes`, and past that you start losing
              patience (you get accustomed to the luxury). Eating is wide; addictive
              things are tight.
    """

    mode: Literal["fixed", "parabola"] = "fixed"
    points: float = Field(default=-2, ge=-100, le=100)
    idealMinutes: int = Field(default=30, ge=1, le=1440)
    widthMinutes: int = Field(default=60, ge=1, le=1440)


class PatienceEntry(BaseModel):
    id: str
    at: str  # UTC ISO, when it happened (or was first recorded)
    date: str  # local YYYY-MM-DD
    amount: float  # + emission, - absorption
    kind: PatienceKind
    source: PatienceSource
    label: str
    tags: list[str] = Field(default_factory=list)
    activityKey: str | None = None  # tasks: what "the same activity" means for averaging
    chapterId: str | None = None
    optionId: str | None = None
    minutes: int | None = None
    expected: float | None = None  # tasks: the before check-in
    actual: float | None = None  # tasks: the after check-in
    settled: bool = True  # tasks stay unsettled until the after check-in
    count: int | None = None  # "open": times the app was checked that day


class PatienceSummary(BaseModel):
    balance: float
    startedAt: str
    interestPerHour: float
    emittedToday: float
    absorbedToday: float
    unsettled: int
    entries: list[PatienceEntry]


class PatienceTaskIn(BaseModel):
    date: str
    chapterId: str
    optionId: str
    phase: Literal["before", "after"]
    amount: float = Field(ge=-100, le=100)
    minutes: int | None = Field(default=None, ge=0, le=1440)


class PatienceLogIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=-100, le=100)
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=10)
    minutes: int | None = Field(default=None, ge=0, le=1440)


class PatienceSuggestion(BaseModel):
    amount: float
    basis: Literal["history", "tag", "need", "average", "fallback"]
    samples: int = 0  # how many past scores the average is over
    profile: TagPatience | None = None  # set for wants & needs, so the UI can redo the parabola
    minutes: int | None = None
    label: str = ""
    tags: list[str] = Field(default_factory=list)


DayPlan.model_rebuild()
UserSettings.model_rebuild()
