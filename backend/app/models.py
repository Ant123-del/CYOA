"""API / storage models (camelCase, matching the frontend)."""

from typing import Literal

from pydantic import BaseModel, Field

GoalStatus = Literal["backlog", "todo", "doing", "done"]
Priority = Literal["high", "medium", "low"]
OptionKind = Literal["yes", "yes_and", "no", "no_and", "route"]
ChapterSource = Literal["calendar", "goal", "custom"]


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


class Chapter(BaseModel):
    id: str
    start: str  # HH:MM local time
    end: str  # HH:MM local time
    title: str
    priority: Priority = "medium"
    source: ChapterSource = "custom"
    calendarEventId: str | None = None
    options: list[Option] = Field(default_factory=list)
    chosenOptionId: str | None = None
    chosenAt: str | None = None
    scheduledEventId: str | None = None


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
    chapters: list[Chapter] = Field(default_factory=list)
    updatedAt: str | None = None


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
    sleepTargetHours: float = 8.0


class UserSettingsPatch(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    sleepTargetHours: float | None = Field(default=None, ge=4, le=12)
    reminderLeadMinutes: int | None = Field(default=None, ge=0, le=240)
    emailReminders: bool | None = None
    # Reminders may only go to the user's own verified sign-in email (checked in the route),
    # so CYOA can't be used to send mail to other people's inboxes.
    notifyEmail: str | None = Field(default=None, max_length=254)
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
