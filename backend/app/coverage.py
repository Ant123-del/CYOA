"""Safety net: every timed calendar event appears in the plan.

The AI sometimes drops long events (e.g. a 5-hour "availability" block) because it wants
meals, breaks or focus blocks inside that time and chapters can't overlap. After it answers,
`ensure_events` checks each timed event the plan was given:
  - covered by a calendar chapter (same calendarEventId, or same title in that time) -> fine
  - otherwise the event takes back its time:
      * goal / custom blocks the AI put mostly inside the event become parts of the event:
        "Yes" (attend), "Yes, and" (attend + that block's work), and the block's original
        options stay as alternatives - so nothing the AI planned is lost
      * free time inside the span becomes more parts (yes / yes-and / no / no-and)
      * meals, breaks and other calendar events are left alone
  - if nothing could be used, a "Go to <event>" path is added to the overlapping chapter,
    so attending stays a choice.
"""

from .meals import to_hm, to_min
from .models import Chapter, DayPlan, Option
from .timeutil import new_id

MIN_PART = 15


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())[:24]


def _covered(plan: DayPlan, ev: dict) -> bool:
    s, e = to_min(ev["start"]), to_min(ev["end"])
    key = _norm(ev["summary"])
    for c in plan.chapters:
        if c.calendarEventId == ev["id"]:
            return True
        overlaps = to_min(c.start) < e and to_min(c.end) > s
        if overlaps and key and key in _norm(c.title):
            return True
    return False


def _free(plan: DayPlan, lo: int, hi: int) -> list[tuple[int, int]]:
    gaps, cur = [], lo
    for s, e in sorted((to_min(c.start), to_min(c.end)) for c in plan.chapters):
        if e <= cur:
            continue
        if s > cur:
            gaps.append((cur, min(s, hi)))
        cur = max(cur, e)
        if cur >= hi:
            break
    if cur < hi:
        gaps.append((cur, hi))
    return [(a, b) for a, b in gaps if b - a >= MIN_PART]


def _options(ev: dict, minutes: int, plan: DayPlan) -> list[Option]:
    name = ev["summary"]
    sls = plan.storylines
    templates = [
        ("yes", f"Go: {name}", "Stick with the plan."),
        ("yes_and", f"{name} + something useful", "Attend, and fit in prep, notes or a small task alongside."),
        ("no", "Skip it, do something else", "Swap in a task of the same priority."),
        ("no_and", "Skip it, and recover the value", "Do an alternative and catch up on what you missed later."),
    ]
    return [
        Option(
            id=new_id(),
            kind=kind,
            storylineId=sls[i % len(sls)].id if sls else None,
            title=title,
            detail=detail,
            durationMinutes=minutes,
        )
        for i, (kind, title, detail) in enumerate(templates)
    ]


def ensure_events(plan: DayPlan, events: list[dict]) -> list[str]:
    """Add any timed event the AI left out. Returns notes about what was added."""
    notes = []
    for ev in events:
        if ev.get("allDay") or ev.get("createdByCyoa") or _covered(plan, ev):
            continue
        s, e = to_min(ev["start"]), to_min(ev["end"])
        if e <= s:
            continue
        # Goal/custom blocks mostly inside the event become parts of it.
        absorbed = [
            c
            for c in plan.chapters
            if c.source in ("goal", "custom")
            and (min(e, to_min(c.end)) - max(s, to_min(c.start))) * 2 >= to_min(c.end) - to_min(c.start)
        ]
        free = _free(plan, s, e)
        if absorbed or free:
            for c in absorbed:
                original = [o for o in c.options if o.kind == "route"] or c.options
                first = original[0] if original else None
                c.options = [
                    Option(
                        id=new_id(),
                        kind="yes",
                        storylineId=None,
                        title=f"Go: {ev['summary']}",
                        detail="Stick with the plan.",
                        durationMinutes=to_min(c.end) - to_min(c.start),
                    ),
                    *(
                        [
                            Option(
                                id=new_id(),
                                kind="yes_and",
                                storylineId=first.storylineId,
                                title=f"{ev['summary']} + {first.title}"[:80],
                                detail=f"Attend, and use the time for: {first.detail or first.title}",
                                durationMinutes=first.durationMinutes,
                                goalIds=first.goalIds,
                            )
                        ]
                        if first
                        else []
                    ),
                    *original,  # the AI's plans for this time stay available
                ]
                c.title = f"{ev['summary']} · {c.title}"
                c.source = "calendar"
                c.calendarEventId = ev["id"]
                c.calendarId = ev.get("calendarId")
                c.calendarName = ev.get("calendarName")
                c.calendarColor = ev.get("color")
            for a, b in free:
                plan.chapters.append(
                    Chapter(
                        id=new_id(),
                        start=to_hm(a),
                        end=to_hm(b),
                        title=ev["summary"],
                        source="calendar",
                        calendarEventId=ev["id"],
                        calendarId=ev.get("calendarId"),
                        calendarName=ev.get("calendarName"),
                        calendarColor=ev.get("color"),
                        activityId=f"event:{ev['id']}",
                        options=_options(ev, b - a, plan),
                    )
                )
            notes.append(f"restored '{ev['summary']}' ({len(absorbed)} block(s) folded in, {len(free)} free slot(s))")
            continue
        overlapping = [c for c in plan.chapters if to_min(c.start) < e and to_min(c.end) > s]
        if overlapping:
            target = overlapping[0]
            target.options.append(
                Option(
                    id=new_id(),
                    kind="route",
                    title=f"Go to {ev['summary']}",
                    detail=f"It's on your calendar {ev['start']}–{ev['end']} - this path means attending it instead.",
                    durationMinutes=min(e, to_min(target.end)) - max(s, to_min(target.start)),
                )
            )
            notes.append(f"offered '{ev['summary']}' inside '{target.title}' (no free time)")
    plan.chapters.sort(key=lambda c: c.start)
    return notes


def _copy_chapter(c: Chapter, start: int, end: int, title: str) -> Chapter:
    return c.model_copy(
        update={
            "id": new_id(),
            "start": to_hm(start),
            "end": to_hm(end),
            "title": title,
            "options": [o.model_copy(update={"id": new_id()}) for o in c.options],
        },
        deep=True,
    )


def resolve_overlaps(plan: DayPlan, max_passes: int = 40) -> list[str]:
    """Make sure no two chapters on one timeline overlap.

    - a meal / block inside a long event (60+ min): the event is split around it
      (Availability -> Lunch -> Availability (cont.)), so both happen
    - a block overlapping a short event: the block is trimmed, or moved just after it
    - two flexible blocks: the later one starts when the earlier one ends
    Two calendar events that really overlap are left alone (that's the calendar).
    """
    notes: list[str] = []
    for _ in range(max_passes):
        chs = sorted(plan.chapters, key=lambda c: (c.start, c.end))
        clash = next(((a, b) for a, b in zip(chs, chs[1:]) if to_min(a.end) > to_min(b.start)), None)
        if not clash:
            break
        a, b = clash
        if a.source == "calendar" and b.source == "calendar":
            # genuinely overlapping events - leave them, but make sure the loop moves on
            later = [c for c in chs if to_min(c.start) >= to_min(b.start) and c is not b]
            if not any(to_min(x.end) > to_min(y.start) for x, y in zip(later, later[1:])):
                break
            continue
        if a.source == "calendar" or b.source == "calendar":
            cal, flex = (a, b) if a.source == "calendar" else (b, a)
            cs, ce, fs, fe = to_min(cal.start), to_min(cal.end), to_min(flex.start), to_min(flex.end)
            if ce - cs >= 60 and fs >= cs and fe <= ce:
                parts = []
                if fs - cs >= 10:
                    parts.append(_copy_chapter(cal, cs, fs, cal.title))
                if ce - fe >= 10:
                    parts.append(_copy_chapter(cal, fe, ce, f"{cal.title} (cont.)"))
                plan.chapters = [c for c in plan.chapters if c is not cal] + parts
                notes.append(f"split '{cal.title}' around '{flex.title}'")
            elif fs < cs and cs - fs >= 15:
                flex.end = cal.start
                notes.append(f"trimmed '{flex.title}' to end before '{cal.title}'")
            elif fe > ce and fe - ce >= 15:
                flex.start = cal.end
                notes.append(f"trimmed '{flex.title}' to start after '{cal.title}'")
            else:
                dur = fe - fs
                flex.start, flex.end = to_hm(ce), to_hm(min(ce + dur, 23 * 60 + 59))
                notes.append(f"moved '{flex.title}' after '{cal.title}'")
        else:
            first, second = a, b
            if to_min(second.end) - to_min(first.end) >= 15:
                second.start = first.end
            else:
                dur = to_min(second.end) - to_min(second.start)
                second.start, second.end = first.end, to_hm(min(to_min(first.end) + dur, 23 * 60 + 59))
            notes.append(f"shifted '{second.title}' after '{first.title}'")
    plan.chapters.sort(key=lambda c: c.start)
    return notes
