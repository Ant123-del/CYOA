"""API / storage models (camelCase, matching the frontend)."""

from typing import Literal

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

ManifestationKind = Literal["negative", "positive"]


class ManifestationIn(BaseModel):
    kind: ManifestationKind
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    corrected: str = Field(default="", max_length=600)  # negative only: the words to repeat to yourself


class ManifestationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    corrected: str | None = Field(default=None, max_length=600)


class Manifestation(ManifestationIn):
    id: str
    createdAt: str | None = None
    updatedAt: str | None = None


class CorrectedSuggestIn(BaseModel):
    title: str = Field(default="", max_length=120)
    description: str = Field(min_length=1, max_length=4000)


class CorrectedSuggestions(BaseModel):
    suggestions: list[str]


DayPlan.model_rebuild()
