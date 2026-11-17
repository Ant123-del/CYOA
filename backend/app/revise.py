"""Revise a day with the AI - small, cheap edits instead of a full regenerate.

The person writes feedback ("commute is ~10 min, add travel time"). The AI sees a compact
version of the plan (short refs, option titles only) and returns just a list of EDITS plus
a short reply - typically a few hundred tokens instead of a whole new day. It can work on
all timelines or one, and can rewrite a single timeline from scratch.

Rules enforced here, whatever the model returns:
  - chosen or missed chapters are locked (the past isn't rewritten)
  - calendar events keep their real times and aren't deleted
  - edits outside the requested timeline are ignored
  - meals stay guaranteed and nothing on a timeline overlaps afterwards
"""

import json
import re
from typing import Literal

from pydantic import BaseModel

from . import ai, coverage, meals
from .models import Chapter, DayPlan, Revision, UserSettings
from .timeutil import new_id, now_iso

HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class AIEdit(BaseModel):
    op: Literal["update", "delete", "add"]
    chapter_ref: str  # existing chapter ("c3") for update/delete; "" for add
    timeline_ref: str  # for add: which timeline ("t0"); "" otherwise
    start: str  # HH:MM, or "" to keep
    end: str  # HH:MM, or "" to keep
    title: str  # "" to keep
    source: Literal["goal", "custom", "meal", "break", "none"]  # for add; "none" otherwise
    activity_key: str  # for add; "" otherwise
    replace_options: bool  # update: replace the options with `options`
    options: list[ai.AIOption]  # for add, or update with replace_options; [] otherwise


class AIRevision(BaseModel):
    reply: str  # 1-3 sentences to the person: what changed (or a question if unclear)
    edits: list[AIEdit]
    memory: ai.AIMemoryUpdate


INSTRUCTIONS = """You are revising an existing CYOA plan together with the person - they gave
feedback on it. Make the SMALLEST set of edits that properly addresses the feedback; leave
everything else exactly as it is. Don't regenerate the day.

- Chapters marked locked=true (already chosen or missed) must not be edited or deleted.
- Calendar events (fixed=true) keep their times and can't be deleted; you may adjust the
  chapters around them (e.g. add travel time before/after, shorten a neighbour).
- Only edit chapters on the timelines in scope. Keep each timeline's role (healthy /
  recovery / rebel) and keep meals. Event-free timelines stay event-free.
- update: give chapter_ref and only the fields that change ("" keeps a field; set
  replace_options=true with new options only if the options themselves must change).
- add: give timeline_ref, start, end, title, source (not "none"), activity_key and options (kind="route",
  storyline_key from the storylines, next_timeline_key "" or a timeline key).
- delete: give chapter_ref.
- Within a timeline chapters must not overlap after your edits - shift neighbours as needed.
- reply: one to three friendly sentences telling them what you changed. If the feedback is
  unclear, make your best reasonable edit and ask one short question.
- memory.learned: if the feedback reveals a durable fact about them (e.g. "Commute is about
  10 minutes each way", "Prefers lunch after 1pm"), record it so future days get it right.
"""


def _compact(plan: DayPlan, scope: set[str | None]) -> tuple[dict, dict[str, Chapter], dict[str, str]]:
    tl_refs = {t.id: f"t{i}" for i, t in enumerate(plan.timelines)}
    sl_refs = {s.id: f"s{i}" for i, s in enumerate(plan.storylines)}
    refs: dict[str, Chapter] = {}
    timelines = []
    groups = [(t.id, t) for t in plan.timelines] or [(None, None)]
    for tid, t in groups:
        chs = sorted((c for c in plan.chapters if c.timelineId == tid), key=lambda c: c.start)
        items = []
        for c in chs:
            ref = f"c{len(refs)}"
            refs[ref] = c
            items.append(
                {
                    "ref": ref,
                    "start": c.start,
                    "end": c.end,
                    "title": c.title,
                    "source": c.source,
                    **({"fixed": True} if c.source == "calendar" else {}),
                    **({"locked": True} if c.chosenOptionId or c.missed else {}),
                    "options": [o.title for o in c.options],
                }
            )
        timelines.append(
            {
                "key": tl_refs.get(tid, "t0"),
                "name": t.name if t else "Your day",
                "role": t.role if t else None,
                "in_scope": tid in scope,
                "chapters": items if tid in scope else [f"{c.start}-{c.end} {c.title}" for c in chs],
            }
        )
    view = {
        "date": plan.date,
        "day_start": plan.dayStart,
        "day_end": plan.dayEnd,
        "storylines": [{"key": sl_refs[s.id], "name": s.name} for s in plan.storylines],
        "timelines": timelines,
    }
    return view, refs, {v: k for k, v in tl_refs.items()}


def revise(
    *,
    plan: DayPlan,
    settings: UserSettings,
    feedback: str,
    timeline_id: str | None,
    rewrite: bool,
    memory_ctx: dict,
    sleep_ctx: dict,
) -> tuple[DayPlan, str, int, ai.MemoryUpdate]:
    """Apply the person's feedback. Returns (plan, reply, edits_applied, memory update)."""
    valid_tls = {t.id for t in plan.timelines}
    scope: set[str | None] = {timeline_id} if timeline_id in valid_tls else (valid_tls or {None})
    view, refs, tl_key_to_id = _compact(plan, scope)

    task = feedback
    if rewrite and timeline_id in valid_tls:
        task = (
            "Rewrite this timeline from scratch for the same role: delete its unlocked non-event "
            "chapters and add a fresh set. " + feedback
        )
    context = {
        "feedback": task,
        "recent_conversation": [
            {"they_said": r.feedback, "you_replied": r.reply} for r in plan.revisions[-4:]
        ],
        "plan": view,
        "priorities_they_gave": plan.priorities,
        "meal_notes": settings.mealNotes or "(none)",
        "sleep": sleep_ctx,
        "memory": memory_ctx,
    }
    result: AIRevision = ai._call(AIRevision, INSTRUCTIONS + "\n\n" + json.dumps(context, indent=1))

    sl_key_to_id = {f"s{i}": s.id for i, s in enumerate(plan.storylines)}
    applied = 0
    for e in result.edits:
        if e.op in ("update", "delete"):
            ch = refs.get(e.chapter_ref.strip())
            if not ch or ch.timelineId not in scope or ch.chosenOptionId or ch.missed:
                continue
            if e.op == "delete":
                if ch.source == "calendar":
                    continue
                plan.chapters = [c for c in plan.chapters if c.id != ch.id]
                applied += 1
                continue
            changed = False
            if ch.source != "calendar":  # events keep their real times
                if HM.match(e.start or ""):
                    ch.start, changed = e.start, True
                if HM.match(e.end or ""):
                    ch.end, changed = e.end, True
            if e.title.strip():
                ch.title, changed = e.title.strip()[:120], True
            if e.replace_options and e.options:
                ch.options = ai._convert_options(e.options, sl_key_to_id, set(), tl_key_to_id, ch.timelineId)
                changed = True
            applied += changed
        elif e.op == "add":
            tid = tl_key_to_id.get(e.timeline_ref.strip()) if plan.timelines else None
            if tid not in scope or not (HM.match(e.start) and HM.match(e.end)) or e.end <= e.start or not e.options:
                continue
            plan.chapters.append(
                Chapter(
                    id=new_id(),
                    start=e.start,
                    end=e.end,
                    title=(e.title or "New chapter")[:120],
                    source=e.source if e.source != "none" else "custom",
                    timelineId=tid,
                    activityId=re.sub(r"[^a-z0-9:_-]+", "-", e.activity_key.lower()).strip("-") or new_id(),
                    options=ai._convert_options(e.options, sl_key_to_id, set(), tl_key_to_id, tid),
                )
            )
            applied += 1

    # Same guarantees as a fresh plan, for every timeline we touched.
    windows = meals.meal_windows(settings, plan.dayStart, plan.dayEnd, sleep_ctx.get("woke_at_local"), plan.date)
    untouched = [c for c in plan.chapters if c.timelineId not in scope]
    rebuilt = []
    for tid in scope:
        track = plan.model_copy(update={"chapters": [c for c in plan.chapters if c.timelineId == tid]})
        meals.ensure_meals(track, windows)
        coverage.resolve_overlaps(track)
        for c in track.chapters:
            c.timelineId = tid
        rebuilt.extend(track.chapters)
    plan.chapters = sorted(untouched + rebuilt, key=lambda c: (c.timelineId or "", c.start))

    reply = result.reply.strip() or "Done."
    plan.revisions = [
        *plan.revisions[-19:],
        Revision(at=now_iso(), feedback=feedback, timelineId=timeline_id if timeline_id in valid_tls else None, reply=reply, applied=applied),
    ]
    return plan, reply, applied, ai.MemoryUpdate(**result.memory.model_dump())
