"""Claude-powered day planning.

Claude returns a structured plan (validated by Pydantic via `messages.parse`):
a few parallel *storylines* (routes through the day) and a sequence of
*chapters* (decision points), each offering several same-priority options.
"""

import json
import re
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel

from .config import get_settings
from .models import Chapter, DayPlan, Option, Storyline, Timeline
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
    next_timeline_key: str  # "" = stay on this timeline; otherwise switch to that timeline


class AIChapter(BaseModel):
    start: str  # HH:MM
    end: str  # HH:MM
    title: str
    priority: Literal["high", "medium", "low"]
    source: Literal["calendar", "goal", "custom", "meal", "break"]
    calendar_event_id: str  # "" when not tied to a calendar event
    activity_key: str  # what this is, shared across timelines ("chem-study", "meal:lunch", "event:<id>")
    options: list[AIOption]


class AITimeline(BaseModel):
    key: str
    name: str
    description: str
    kept_event_ids: list[str]  # calendar_event_ids of the anchors this timeline keeps
    chapters: list[AIChapter]


class AIMemoryUpdate(BaseModel):
    learned: list[str]  # 0-3 new, durable observations about the person
    outdated_note_ids: list[str]  # ids of your own notes that are now wrong or superseded


class AIPlan(BaseModel):
    summary: str
    storylines: list[AIStoryline]
    anchors: list[AIChapter]  # calendar-event chapters, written once - shared by every timeline
    timelines: list[AITimeline]  # flexible chapters only (goal / custom / meal / break)
    memory: AIMemoryUpdate


class AIOptionList(BaseModel):
    options: list[AIOption]
    memory: AIMemoryUpdate


class MemoryUpdate(BaseModel):
    learned: list[str] = []
    outdated_note_ids: list[str] = []


SYSTEM_PROMPT = """You are the planner inside CYOA ("Choose Your Own Adventure"), a productivity app.

CYOA's philosophy: rigid routines break when the day goes sideways. Instead of one fixed
schedule, you build a day that is a branching story. The user still has a plan, but at every
decision point ("chapter") they get several equally-valid options of the SAME priority, so
there's always a good backup when plan A goes south.

How to build the day - TIMELINES woven together by STORYLINES:
- A day is not one schedule. Build number_of_timelines TIMELINES: complete versions of the
  SAME day, each a full chronological list of chapters from day_start to day_end. Each has a
  fixed ROLE, in this order (see timeline_roles; with 2 timelines, only the first two):
    1. "healthy" - the PERFECT HEALTHY ROUTINE: the ideal, balanced version of today. Keeps
       EVERY calendar event, makes steady progress on the top goals, and has proper meals,
       movement, real breaks and a calm wind-down. The day they'd be proud of.
    2. "recovery" - CATCH-UP / RECOVERY: for when they're behind or running low. Catches up
       on what slipped (overdue or neglected goals, things recent_days show they skipped)
       and protects energy: rest, lighter blocks, an early night.
    3. "rebel" - the REBEL DAY: just being human. Hardly anything important gets done; it's
       hanging out, hobbies, games, a long walk, a nap, seeing friends, doing nothing. Still
       eats real meals. Warm, never guilt-trippy.
  Give each a short evocative name that fits its role and a one-sentence description. The
  activities overlap where it makes sense (meals, maybe a short goal block), but each
  timeline arranges its day its own way - order, start times and lengths.
- activity_key says WHAT a chapter is, and it is shared across timelines: the same activity
  on every timeline uses the same key ("chem-study", "phil-essay", "gym", "meal:lunch",
  "meal:dinner", "break:afternoon"). Anchors use "event:<calendar_event_id>". Each timeline
  should cover the same flexible activity_keys. If you split an activity into parts, use
  the same parts ("chem-study:1", "chem-study:2") on every timeline.
- Calendar events are ANCHORS. Write each anchor chapter ONCE in "anchors" (never inside a
  timeline), at its real time. Each timeline lists the anchors it keeps in kept_event_ids;
  the app places those on that timeline. Timelines contain only flexible chapters (source
  "goal", "custom", "meal", "break") fitted around the anchors they keep.
- ONLY the healthy timeline has calendar events - it keeps every one. The recovery and rebel
  timelines have NO calendar events at all (kept_event_ids = []): plan them as if the
  calendar were cleared, using the whole day their own way. Don't recreate events there as
  ordinary chapters either.
- Timelines MUST be genuinely different. Besides skipping different events, no two timelines
  may have the same flexible chapters at the same times: change the order (gym before study on one, after on another),
  the timing, the lengths, and how work is chunked. Copying a timeline is a failure. Even on
  a packed day, use every free gap differently.
- Within ONE timeline chapters never overlap (including with the anchors). Chapters on different timelines may overlap
  freely (they are alternatives). Leave a few minutes for transitions. Chapters are
  HH:MM 24-hour times in the user's local timezone, typically 30-90 minutes.
- STORYLINES are threads that weave the timelines together - not separate schedules. Create
  number_of_storylines of them (e.g. "Chem push", "Recovery", "Social"), meaningfully
  different, each still making progress on the user's priorities. Every option belongs to a
  storyline (storyline_key) and decides where the day goes next with next_timeline_key:
  "" to continue on the same timeline, or another timeline's key to switch to it once this
  chapter ends. Use switches with intent: an option that leaves them drained leads to the
  gentler timeline; finishing something early leads to the timeline that tackles the next
  thing sooner. Say where it leads in the detail ("...then switch to Ease in: gym next,
  chem tonight").
- After a switch the person continues on the target timeline from this chapter's end time,
  and anything they've already done (same activity_key) is skipped there - so make sure the
  target timeline's later chapters still make sense from that point.
- Every chapter offers 2-4 options from different storylines. In most non-anchor chapters at
  least one option stays and at least one switches timelines. Every storyline should show up
  throughout the day on every timeline, so a thread can be followed from morning to night.
- Anchor chapters (in "anchors": source="calendar", calendar_event_id set) MUST offer these
  four options (one each, in this order), each with its own storyline_key and
  next_timeline_key (switching from an anchor means: after this event, continue on that
  timeline):
    * kind="yes":     do the event as planned.
    * kind="yes_and": do the event AND attach something useful (prep, follow-up, combine with a goal).
    * kind="no":      skip/decline it and do a specific alternative of similar priority instead.
    * kind="no_and":  skip it, do an alternative AND something extra (recover the value another way).
  You may add more options with kind="route" if genuinely useful.
  All-day events are context, not chapters (mention them in option details if relevant).
  EVERY timed (non-all-day) event in calendar_events must appear in "anchors" - never
  drop one, and never replace one with goal work (put goal work in its yes_and / no options
  instead). Long events (over ~2 hours, e.g. availability windows, shifts, fairs, office
  hours) may be split into consecutive chapters with the same calendar_event_id, titled
  "<event> (part 1)", "<event> (part 2)"..., so meals and breaks fit between the parts. If two
  events overlap, both still appear (shorten or split one so chapters don't overlap).
  Events can come from several of the user's calendars (e.g. Work, Personal, Family); each
  event's "calendar" field names it. Use it as context (a Work meeting vs a family event
  deserve different alternatives), and if two calendars hold the same event, make one chapter.
- Other chapters (source="goal", "custom", "meal" or "break") use kind="route" options. Pull
  them from the user's goals (put the goal ids in goal_ids) and their stated priorities.
- Goals are long-term. A goal's total_effort_minutes is its TOTAL effort, usually spread over many
  days - never try to finish a goal in one day. Plan a realistic slice today for the goals
  that matter most now (higher priority and nearer due dates first); lower-priority goals can
  get no time today. Daily limits per goal, counting all its blocks on that timeline:
  healthy at most ~2 hours, recovery at most ~1.5 hours (catch-up items first), rebel at most
  ~30 minutes and only if it's light. A free day is NOT a reason to fill every hour - open,
  unscheduled time (free time, rest, social, a hobby) is healthy and should show up as such.
- storyline_key on every option must match one of your storylines' keys, and
  next_timeline_key must be "" or one of your timelines' keys.
- Titles are short and actionable (max ~8 words). Details are ONE short concrete sentence
  (max ~20 words) - keep the whole answer compact.
- duration_minutes is how long that option takes; keep it within the chapter when possible.
- summary: two or three upbeat sentences: the timelines on offer and how the storylines let
  them move between them.

Meals (the "meals" field) - people need to eat, every day, on every route:
- On EVERY timeline, every meal listed in "meals" MUST be its own chapter with source="meal",
  activity_key "meal:<breakfast|lunch|dinner>", titled with the
  meal ("Lunch", "Dinner"...), starting inside its window_start-window_end, as close to
  preferred_time as the day allows. Lengths: breakfast 15-30 min, lunch 30-60, dinner 30-60.
  Meals not listed (the person turned them off) don't get a chapter.
- A meal chapter is still a choice: 2-4 kind="route" options, one per storyline where
  possible, that are genuinely different ways to eat (cook something proper, quick healthy
  bite, walk out for food, eat with someone, a planned treat). Fit them to the storyline's
  spirit and energy. NEVER offer skipping or postponing the meal as an option.
- Respect meal_notes (diet, habits) in every meal option.
- If calendar events cover a whole meal window, still eat: put the meal in the nearest free
  slot just outside it, and make the conflicting event's "no" or "yes_and" option include
  food explicitly (e.g. "Join camera-off and eat lunch"). Say so in the summary.

Breaks (keep people fresh, without stealing the choice):
- No more than ~90 minutes of focused work in a row. Either build a 10-15 minute break into
  the chapter (option duration_minutes shorter than the chapter, and mention the break in
  the detail) or add a short chapter with source="break" (10-20 min) between long blocks.
- A break chapter also offers 2-3 kind="route" options (e.g. walk outside, stretch and
  water, quiet coffee) - different ways to recharge, never "keep working".
- After back-to-back meetings (60+ minutes with no gap), add a short reset before the next
  focus block.
- Use goal ids exactly as given; use [] when an option isn't tied to a goal.

Sleep (the "sleep" field; tracked=false means no data, so plan normally):
- status is "rested", "low" or "deprived", based on last night vs target_hours and the
  7-day sleep_debt_hours. Let it shape the day:
    * rested: plan normally.
    * low: put the most demanding work in the first few hours after waking, avoid
      back-to-back deep-focus blocks, and make sure one storyline is clearly low-energy.
    * deprived: lighter day overall. Fewer, shorter focus blocks; keep high-priority
      items but give low-effort routes for them; offer a 20-minute rest/nap route in the
      early afternoon; nothing strenuous or safety-critical late in the day.
- If plan_is_for_today and woke_at_local is today, don't start chapters before it.
  hours_awake_now tells you how long they've been up; past ~16 hours, wrap things up.
- Aim to finish the last chapter by wind_down_at so they can be in bed by
  suggested_bedtime, even if day_end is later; a calm wind-down route is a good last
  option. Going to bed at a consistent time matters more than one extra task.
- When sleep shaped the plan, say so briefly and kindly in the summary.

Memory (the "memory" field) - you are the same planner every day, and you know this person:
- what_you_know_about_them: notes from earlier sessions. told_by="them" notes are things
  they told you directly; treat them as firm preferences. told_by="you" are your own
  observations; trust them but update them when evidence changes.
- their_recent_requests: what they asked you for recently (priorities, option hints).
  Notice threads: an unfinished project they keep mentioning, a recurring struggle, a
  goal they keep pushing back.
- recent_days: what actually happened - which paths they took (and passed_on), which
  storylines they favour, and chapters_never_chosen (plans they ignored). patterns
  summarises this. Learn from it: offer more of what they really pick, at the times they
  really do it; make ignored kinds of blocks smaller, move them, or reframe them. Don't
  just repeat yesterday - keep one route that stretches them a little.
- Build on continuity. If something was skipped repeatedly, give it a better shot today.
  If they had a big push yesterday, consider a lighter start. Reference the past
  naturally and briefly in the summary when it helps ("You crushed the Main Quest
  yesterday, so..."), like a coach who remembers - never creepy, never a recap of data.
- Choosing the rebel timeline (or drifting into it) is normal and healthy now and then - never
  treat it as failure, never nag about it, and don't record it as a problem. Only note a
  pattern if it clearly matters to them (e.g. rebel days every time before an exam).
- first_time=true means you're just meeting them: plan from the inputs alone.
- Fill memory.learned with 0-3 short, durable, third-person observations worth
  remembering next time (e.g. "Does their best deep work before 11:00",
  "Usually declines afternoon meetings in favour of async updates",
  "Training for a half marathon in March"). Only new information; never duplicate an
  existing note, never record one-off details for a single day, sensitive data
  (health diagnoses, finances, other people's private info), or anything they'd be
  surprised you kept. [] is a fine answer.
- memory.outdated_note_ids: ids of told_by="you" notes contradicted by newer evidence or
  by something they just said. Usually [].
"""


def _call(output_model: type[BaseModel], user_content: str, max_tokens: int = 16000):
    """Use Gemini when GEMINI_API_KEY is set, otherwise Claude."""
    s = get_settings()
    if s.gemini_api_key:
        return _call_gemini(output_model, user_content, max_tokens)
    if s.anthropic_api_key:
        return _call_claude(output_model, user_content, max_tokens)
    raise AIError("No AI key configured: set GEMINI_API_KEY (or ANTHROPIC_API_KEY) for the backend.")


GEMINI_MAX_OUTPUT_TOKENS = 65536


def _call_gemini(output_model: type[BaseModel], user_content: str, max_tokens: int):
    from google import genai
    from google.genai import errors, types

    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key)  # keep a reference: the client closes its session when collected
    try:
        response = client.models.generate_content(
            model=s.gemini_model,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=output_model,
                # Gemini counts its internal thinking against this limit too, so leave lots of room:
                # a busy day (many events + meals + breaks) easily needs >16k tokens in total.
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[s.gemini_thinking_level.upper()]),
            ),
        )
    except errors.ClientError as exc:
        if exc.code == 429:
            raise AIError("The AI is rate limited right now - try again in a minute.") from exc
        if exc.code == 402:
            raise AIError("Gemini billing: the API key's prepaid credits are used up. Add credit at https://ai.studio/projects.") from exc
        if exc.code in (400, 401, 403) and "API key" in (exc.message or ""):
            raise AIError("GEMINI_API_KEY is invalid.") from exc
        raise AIError(f"AI request failed ({exc.code}): {exc.message}") from exc
    except errors.APIError as exc:
        raise AIError(f"AI service error ({exc.code}): {exc.message}") from exc

    usage = response.usage_metadata
    if usage:
        log.info(
            "Gemini %s usage: input=%s (cached=%s) output=%s thinking=%s",
            output_model.__name__,
            usage.prompt_token_count,
            usage.cached_content_token_count,
            usage.candidates_token_count,
            usage.thoughts_token_count,
        )
    parsed = response.parsed
    if isinstance(parsed, output_model):
        return parsed
    try:
        return output_model.model_validate_json(response.text or "")
    except Exception as exc:
        cand = (response.candidates or [None])[0]
        usage = response.usage_metadata
        log.warning(
            "Unparseable Gemini output (finish_reason=%s, output_tokens=%s, thinking_tokens=%s): %s",
            getattr(cand, "finish_reason", None),
            getattr(usage, "candidates_token_count", None),
            getattr(usage, "thoughts_token_count", None),
            (response.text or "")[-300:],
        )
        raise AIError("The AI response was incomplete - please try again.") from exc


def _call_claude(output_model: type[BaseModel], user_content: str, max_tokens: int):
    s = get_settings()
    try:
        response = anthropic.Anthropic(api_key=s.anthropic_api_key).beta.messages.parse(
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
            "total_effort_minutes": g.get("estimateMinutes"),  # whole goal, across many days
            "due_date": g.get("dueDate"),
            "tags": g.get("tags", []),
        }
        for g in goals
    ]


def _convert_options(
    ai_options: list[AIOption],
    key_to_id: dict[str, str],
    valid_goal_ids: set[str],
    timeline_key_to_id: dict[str, str] | None = None,
    own_timeline_id: str | None = None,
) -> list[Option]:
    tl = timeline_key_to_id or {}
    out = []
    for o in ai_options:
        nxt = tl.get(o.next_timeline_key.strip()) if o.next_timeline_key else None
        out.append(
            Option(
                id=new_id(),
                kind=o.kind,
                storylineId=key_to_id.get(o.storyline_key),
                title=o.title,
                detail=o.detail,
                durationMinutes=o.duration_minutes,
                goalIds=[g for g in o.goal_ids if g in valid_goal_ids],
                nextTimelineId=nxt if nxt and nxt != own_timeline_id else None,
            )
        )
    return out


TIMELINE_ROLES = ["healthy", "recovery", "rebel"]
TIMELINE_COLORS = ["#5b7cfa", "#d9a13b", "#3fa66b", "#b25fd6"]


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _looks_like_event(c: AIChapter, events: list[dict]) -> bool:
    """A flexible chapter that is really a calendar event (same name, overlapping time)."""
    title = _norm(c.title)
    for e in events:
        if not (c.start < e["end"] and c.end > e["start"]):
            continue
        core = re.split(r"[—–(:|]| - ", e["summary"])[0]  # "PHIL 22-01 — Ethical Theory" -> "PHIL 22-01"
        names = {_norm(e["summary"])[:24], _norm(core)}
        if any(len(n) >= 4 and n in title for n in names):
            return True
    return False


def _activity_id(c: AIChapter, is_event: bool) -> str:
    if is_event:
        key = f"event:{c.calendar_event_id}"
        title = c.title.lower()
        part = re.search(r"\(part (\d+)", title)  # split events: one activity per part
        return f"{key}:{part.group(1)}" if part else key
    key = re.sub(r"[^a-z0-9:_-]+", "-", (c.activity_key or "").strip().lower()).strip("-")
    return key or new_id()


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
    sleep: dict | None = None,
    is_today: bool = False,
    memory: dict | None = None,
    meals: list[dict] | None = None,
    meal_notes: str = "",
    timelines: int = 3,
) -> tuple[DayPlan, MemoryUpdate]:
    routes = max(2, min(routes, 4))
    n_timelines = max(2, min(timelines, len(TIMELINE_ROLES)))
    context = {
        "date": date,
        "weekday": weekday,
        "timezone": timezone,
        "day_start": day_start,
        "day_end": day_end,
        "number_of_timelines": n_timelines,
        "timeline_roles": TIMELINE_ROLES[:n_timelines],
        "number_of_storylines": routes,
        "plan_is_for_today": is_today,
        "sleep": sleep or {"tracked": False},
        "memory": memory or {"first_time": True},
        "meals": meals or [],
        "meal_notes": meal_notes or "(none)",
        "user_priorities_for_the_day": priorities or "(none given - infer from goals)",
        "goals": _goal_summary(goals),
        "calendar_events": [
            {**{k: e[k] for k in ("id", "summary", "description", "start", "end", "allDay")}, "calendar": e.get("calendarName", "")}
            for e in events
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
    events_by_id = {e["id"]: e for e in events}
    valid_event_ids = set(events_by_id)

    all_event_ids = [e["id"] for e in events if not e.get("allDay")]
    timelines: list[Timeline] = []
    tl_key_to_id: dict[str, str] = {}
    kept_by_tl: dict[str, set[str]] = {}
    for i, t in enumerate(plan.timelines[:n_timelines]):
        tid = new_id()
        tl_key_to_id[t.key.strip()] = tid
        # Only the first (healthy) timeline has calendar events; the others have none.
        kept = set(all_event_ids) if i == 0 else set()
        kept_by_tl[tid] = kept
        timelines.append(
            Timeline(
                id=tid,
                name=t.name,
                description=t.description,
                color=TIMELINE_COLORS[i % len(TIMELINE_COLORS)],
                role=TIMELINE_ROLES[i],
                keptEventIds=sorted(kept),
                skippedEvents=[e["summary"] for e in events if not e.get("allDay") and e["id"] not in kept],
            )
        )

    chapters: list[Chapter] = []
    for t in plan.timelines[:n_timelines]:
        tid = tl_key_to_id[t.key.strip()]
        kept = kept_by_tl[tid]
        anchors = [a for a in plan.anchors if a.calendar_event_id in kept]
        flexible = [c for c in t.chapters if c.source != "calendar"]  # anchors come from plan.anchors
        if not kept:  # event-free timeline: drop events the model re-added as ordinary chapters
            flexible = [c for c in flexible if not _looks_like_event(c, events)]
        for c in sorted([*anchors, *flexible], key=lambda c: c.start):
            is_event = c.source == "calendar" and c.calendar_event_id in valid_event_ids
            ev = events_by_id.get(c.calendar_event_id, {}) if is_event else {}
            chapters.append(
                Chapter(
                    id=new_id(),
                    start=c.start,
                    end=c.end,
                    title=c.title,
                    priority=c.priority,
                    source=c.source if (c.source != "calendar" or is_event) else "custom",
                    calendarEventId=c.calendar_event_id if is_event else None,
                    calendarId=ev.get("calendarId"),
                    calendarName=ev.get("calendarName"),
                    calendarColor=ev.get("color"),
                    timelineId=tid,
                    # Same activity on every timeline -> same id, so doing it once counts everywhere.
                    activityId=_activity_id(c, is_event),
                    options=_convert_options(c.options, key_to_id, valid_goal_ids, tl_key_to_id, tid),
                )
            )
    day = DayPlan(
        date=date,
        priorities=priorities,
        dayStart=day_start,
        dayEnd=day_end,
        summary=plan.summary,
        storylines=storylines,
        timelines=timelines,
        currentTimelineId=timelines[0].id if timelines else None,
        chapters=chapters,
    )
    return day, MemoryUpdate(**plan.memory.model_dump())


def regenerate_options(
    *,
    day: DayPlan,
    chapter: Chapter,
    goals: list[dict],
    hint: str,
    sleep: dict | None = None,
    memory: dict | None = None,
    meal_notes: str = "",
) -> tuple[list[Option], MemoryUpdate]:
    id_to_key = {s.id: f"s{i}" for i, s in enumerate(day.storylines)}
    key_to_id = {v: k for k, v in id_to_key.items()}
    tl_to_key = {t.id: f"t{i}" for i, t in enumerate(day.timelines)}
    tl_key_to_id = {v: k for k, v in tl_to_key.items()}

    def schedule(tid):
        return [f"{c.start}-{c.end} {c.title}" for c in sorted(day.chapters, key=lambda c: c.start) if c.timelineId == tid and c.id != chapter.id]

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
        "this_chapter_timeline": tl_to_key.get(chapter.timelineId, ""),
        "timelines": [
            {"key": tl_to_key[t.id], "name": t.name, "description": t.description, "chapters": schedule(t.id)}
            for t in day.timelines
        ],
        "other_chapters_today": [] if day.timelines else [f"{c.start}-{c.end} {c.title}" for c in day.chapters if c.id != chapter.id],
        "goals": _goal_summary(goals),
        "user_hint": hint or "(none) - offer fresh alternatives",
        "meal_notes": meal_notes or "(none)",
        "sleep": sleep or {"tracked": False},
        "memory": memory or {"first_time": True},
    }
    rules = {
        "calendar": "This is a calendar chapter: return exactly the four kinds yes, yes_and, no, no_and (plus optional route).",
        "meal": "This is a meal chapter: return 2-4 kind='route' options that are different ways to eat this meal "
        "(follow meal_notes); never offer skipping or postponing it.",
        "break": "This is a break chapter: return 2-3 kind='route' options that are different ways to recharge; "
        "never 'keep working'.",
    }
    rule = rules.get(chapter.source, "Return 2-4 options with kind='route', one per storyline where possible, same priority.")
    if day.timelines:
        rule += (
            " Set next_timeline_key on each option: \"\" to stay on this_chapter_timeline, or another"
            " timeline's key to switch there after this chapter - keep at least one that stays and,"
            " where it makes sense, one that switches."
        )
    else:
        rule += " This day has no timelines: set next_timeline_key to \"\" on every option."
    result: AIOptionList = _call(
        AIOptionList,
        f"Write new options for ONE chapter of an existing day. {rule}\n\n" + json.dumps(context, indent=2),
        max_tokens=8000,
    )
    options = _convert_options(result.options, key_to_id, {g["id"] for g in goals}, tl_key_to_id, chapter.timelineId)
    return options, MemoryUpdate(**result.memory.model_dump())
