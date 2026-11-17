"""Claude-powered day planning.

Claude returns a structured plan (validated by Pydantic via `messages.parse`):
a few parallel *storylines* (routes through the day) and a sequence of
*chapters* (decision points), each offering several same-priority options.
"""

import json
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel

from .config import get_settings
from .models import Chapter, DayPlan, Option, Storyline
from .timeutil import new_id

log = logging.getLogger("cyoa.ai")

STORYLINE_COLORS = ["#7c5cff", "#16a394", "#e8833a", "#d6457a", "#3b82f6"]


class AIError(Exception):
    pass


# ---------- structured output schema ----------


class AIStoryline(BaseModel):
    key: str  # short slug, e.g. "main", "low_energy", "pivot"
    name: str
    description: str


class AIOption(BaseModel):
    kind: Literal["yes", "yes_and", "no", "no_and", "route"]
    storyline_key: str
    title: str
    detail: str
    duration_minutes: int
    goal_ids: list[str]


class AIChapter(BaseModel):
    start: str  # HH:MM
    end: str  # HH:MM
    title: str
    priority: Literal["high", "medium", "low"]
    source: Literal["calendar", "goal", "custom"]
    calendar_event_id: str  # "" when not tied to a calendar event
    options: list[AIOption]


class AIPlan(BaseModel):
    summary: str
    storylines: list[AIStoryline]
    chapters: list[AIChapter]


class AIOptionList(BaseModel):
    options: list[AIOption]


SYSTEM_PROMPT = """You are the planner inside CYOA ("Choose Your Own Adventure"), a productivity app.

CYOA's philosophy: rigid routines break when the day goes sideways. Instead of one fixed
schedule, you build a day that is a branching story. The user still has a plan, but at every
decision point ("chapter") they get several equally-valid options of the SAME priority, so
there's always a good backup when plan A goes south.

How to build the day:
- Create the requested number of storylines (parallel routes through the day). Make them
  meaningfully different. Examples: "Main Quest" (ambitious, deep focus), "Steady Path"
  (moderate energy, keeps momentum), "Side Quest / Pivot" (low energy, errands, or a change
  of scenery). Each storyline should still make progress on the user's priorities.
- Chapters are time blocks between day_start and day_end, in chronological order, with
  HH:MM 24-hour times in the user's local timezone. Do not overlap chapters. Leave
  realistic breaks (meals, transitions). Typical chapter length is 30-120 minutes.
- Calendar events become chapters with source="calendar" and calendar_event_id set to the
  event id. They MUST offer these four options (one each, in this order):
    * kind="yes":     do the event as planned.
    * kind="yes_and": do the event AND attach something useful (prep, follow-up, combine with a goal).
    * kind="no":      skip/decline it and do a specific alternative of similar priority instead.
    * kind="no_and":  skip it, do an alternative AND something extra (recover the value another way).
  You may add more options with kind="route" if genuinely useful.
  All-day events are context, not chapters (mention them in option details if relevant).
- Every other chapter (source="goal" or "custom") offers 2-4 options with kind="route",
  ideally one per storyline, all at the same priority level. Pull these from the user's goals
  (put the goal ids in goal_ids) and from their stated priorities.
- Higher-priority goals belong earlier and in more storylines. Respect due dates and estimates.
- storyline_key on every option must match one of your storylines' keys. For calendar
  options, use the storyline whose spirit fits best.
- Titles are short and actionable (max ~8 words). Details are one or two concrete sentences.
- duration_minutes is how long that option takes; keep it within the chapter when possible.
- summary: two or three upbeat sentences describing the shape of the day and its routes.
- Use goal ids exactly as given; use [] when an option isn't tied to a goal.
"""


def _client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def _call(output_model: type[BaseModel], user_content: str, max_tokens: int = 16000):
    s = get_settings()
    try:
        response = _client().beta.messages.parse(
            model=s.anthropic_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # re-run on a fallback model if the request is declined
            output_config={"effort": "medium"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_format=output_model,
        )
    except anthropic.AuthenticationError as exc:
        raise AIError("Anthropic API key is missing or invalid (set ANTHROPIC_API_KEY in backend/.env).") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("The AI is rate limited right now - try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"AI request failed ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Could not reach the AI service.") from exc

    if response.stop_reason == "refusal":
        raise AIError("The AI declined to plan this request. Try rewording your priorities.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AIError("The AI response was incomplete. Try a shorter day or fewer goals.")
    return response.parsed_output


def _goal_summary(goals: list[dict]) -> list[dict]:
    return [
        {
            "id": g["id"],
            "title": g.get("title", ""),
            "description": (g.get("description") or "")[:300],
            "status": g.get("status"),
            "priority": g.get("priority"),
            "estimate_minutes": g.get("estimateMinutes"),
            "due_date": g.get("dueDate"),
            "tags": g.get("tags", []),
        }
        for g in goals
    ]


def _convert_options(ai_options: list[AIOption], key_to_id: dict[str, str], valid_goal_ids: set[str]) -> list[Option]:
    return [
        Option(
            id=new_id(),
            kind=o.kind,
            storylineId=key_to_id.get(o.storyline_key),
            title=o.title,
            detail=o.detail,
            durationMinutes=o.duration_minutes,
            goalIds=[g for g in o.goal_ids if g in valid_goal_ids],
        )
        for o in ai_options
    ]


def plan_day(
    *,
    date: str,
    weekday: str,
    timezone: str,
    priorities: str,
    day_start: str,
    day_end: str,
    goals: list[dict],
    events: list[dict],
    routes: int,
) -> DayPlan:
    routes = max(2, min(routes, 4))
    context = {
        "date": date,
        "weekday": weekday,
        "timezone": timezone,
        "day_start": day_start,
        "day_end": day_end,
        "number_of_storylines": routes,
        "user_priorities_for_the_day": priorities or "(none given - infer from goals)",
        "goals": _goal_summary(goals),
        "calendar_events": [
            {k: e[k] for k in ("id", "summary", "description", "start", "end", "allDay")} for e in events
        ],
    }
    plan: AIPlan = _call(
        AIPlan,
        "Plan this day as a choose-your-own-adventure.\n\n" + json.dumps(context, indent=2),
    )

    key_to_id: dict[str, str] = {}
    storylines: list[Storyline] = []
    for i, sl in enumerate(plan.storylines):
        sid = new_id()
        key_to_id[sl.key] = sid
        storylines.append(
            Storyline(id=sid, name=sl.name, description=sl.description, color=STORYLINE_COLORS[i % len(STORYLINE_COLORS)])
        )

    valid_goal_ids = {g["id"] for g in goals}
    valid_event_ids = {e["id"] for e in events}
    chapters = [
        Chapter(
            id=new_id(),
            start=c.start,
            end=c.end,
            title=c.title,
            priority=c.priority,
            source=c.source if (c.source != "calendar" or c.calendar_event_id in valid_event_ids) else "custom",
            calendarEventId=c.calendar_event_id if c.calendar_event_id in valid_event_ids else None,
            options=_convert_options(c.options, key_to_id, valid_goal_ids),
        )
        for c in sorted(plan.chapters, key=lambda c: c.start)
    ]
    return DayPlan(
        date=date,
        priorities=priorities,
        dayStart=day_start,
        dayEnd=day_end,
        summary=plan.summary,
        storylines=storylines,
        chapters=chapters,
    )


def regenerate_options(*, day: DayPlan, chapter: Chapter, goals: list[dict], hint: str) -> list[Option]:
    id_to_key = {s.id: f"s{i}" for i, s in enumerate(day.storylines)}
    key_to_id = {v: k for k, v in id_to_key.items()}
    context = {
        "date": day.date,
        "user_priorities_for_the_day": day.priorities,
        "storylines": [{"key": id_to_key[s.id], "name": s.name, "description": s.description} for s in day.storylines],
        "chapter": {
            "start": chapter.start,
            "end": chapter.end,
            "title": chapter.title,
            "priority": chapter.priority,
            "source": chapter.source,
            "current_options": [o.title for o in chapter.options],
        },
        "other_chapters_today": [f"{c.start}-{c.end} {c.title}" for c in day.chapters if c.id != chapter.id],
        "goals": _goal_summary(goals),
        "user_hint": hint or "(none) - offer fresh alternatives",
    }
    rule = (
        "This is a calendar chapter: return exactly the four kinds yes, yes_and, no, no_and (plus optional route)."
        if chapter.source == "calendar"
        else "Return 2-4 options with kind='route', one per storyline where possible, same priority."
    )
    result: AIOptionList = _call(
        AIOptionList,
        f"Write new options for ONE chapter of an existing day. {rule}\n\n" + json.dumps(context, indent=2),
        max_tokens=8000,
    )
    return _convert_options(result.options, key_to_id, {g["id"] for g in goals})
