"""Meals: the windows the planner must respect, and a safety net that guarantees them.

The AI is asked to plan meals as real chapters with several ways to eat (the user still
chooses). After it answers, `ensure_meals` checks every meal window that falls inside the
day; if the AI forgot one, a meal chapter is inserted in the best free slot - with
choices, never a "skip the meal" option. If the day is packed solid through a meal, an
"eat instead" path is added to the block overlapping mealtime, so eating stays a choice
there too.
"""

import re
from datetime import datetime

from .models import Chapter, DayPlan, Option, UserSettings
from .timeutil import new_id

MEAL_RE = re.compile(r"\b(breakfast|brunch|lunch|dinner|supper|meal)\b", re.I)

# How far before / after the preferred time a meal may land.
WINDOW_BEFORE = 60
WINDOW_AFTER = 90
MIN_SLOT = 15

DURATION = {"breakfast": 30, "lunch": 45, "dinner": 60}

# Fallback choices (used only by the safety net). Different ways to eat - never "skip it".
DEFAULT_OPTIONS = {
    "breakfast": [
        ("Sit-down breakfast", "Eat a proper breakfast before diving into the day.", 30),
        ("Quick breakfast", "Something simple and filling - toast, fruit, yogurt, eggs.", 15),
        ("Breakfast walk", "Walk out for breakfast and catch some morning daylight.", 30),
    ],
    "lunch": [
        ("Lunch away from your desk", "A real lunch break, away from screens.", 45),
        ("Quick, healthy lunch", "Something easy that keeps your energy steady.", 20),
        ("Walk out for lunch", "Get outside, move a little, and grab food.", 45),
    ],
    "dinner": [
        ("Cook a proper dinner", "Make something you enjoy and sit down to eat it.", 60),
        ("Easy dinner", "Leftovers or something simple - no fuss.", 30),
        ("Dinner with someone", "Eat with family, friends or housemates.", 60),
    ],
}


def to_min(hm: str) -> int:
    h, m = hm.split(":")[:2]
    return int(h) * 60 + int(m)


def to_hm(m: int) -> str:
    m = max(0, min(m, 23 * 60 + 59))
    return f"{m // 60:02d}:{m % 60:02d}"


def meal_windows(settings: UserSettings, day_start: str, day_end: str, woke_at_local: str | None = None, date: str = "") -> list[dict]:
    """The meals this day should contain, with their windows (HH:MM), clipped to the day."""
    ds, de = to_min(day_start), to_min(day_end)
    prefs = [
        ("breakfast", settings.breakfastEnabled, settings.breakfastTime),
        ("lunch", settings.lunchEnabled, settings.lunchTime),
        ("dinner", settings.dinnerEnabled, settings.dinnerTime),
    ]
    out = []
    for meal, enabled, pref in prefs:
        if not enabled:
            continue
        p = to_min(pref)
        lo, hi = p - WINDOW_BEFORE, p + WINDOW_AFTER
        # Breakfast follows waking: if we know they woke today, aim ~30 min after.
        if meal == "breakfast" and woke_at_local and date and woke_at_local.startswith(date):
            wake = to_min(woke_at_local[-5:])
            p, lo, hi = wake + 30, wake, wake + 120
        lo, hi = max(lo, ds), min(hi, de)
        if hi - lo < MIN_SLOT:
            continue  # this meal falls outside the planned day
        out.append({"meal": meal, "preferred": to_hm(min(max(p, lo), hi)), "window_start": to_hm(lo), "window_end": to_hm(hi)})
    return out


def is_meal_chapter(ch: Chapter) -> bool:
    return ch.source == "meal" or bool(MEAL_RE.search(ch.title or ""))


def _free_gaps(chapters: list[Chapter], lo: int, hi: int) -> list[tuple[int, int]]:
    busy = sorted((to_min(c.start), to_min(c.end)) for c in chapters)
    gaps, cur = [], lo
    for s, e in busy:
        if e <= cur:
            continue
        if s > cur:
            gaps.append((cur, min(s, hi)))
        cur = max(cur, e)
        if cur >= hi:
            break
    if cur < hi:
        gaps.append((cur, hi))
    return [(a, b) for a, b in gaps if b - a >= MIN_SLOT]


def _options(meal: str, plan: DayPlan, max_minutes: int) -> list[Option]:
    sls = plan.storylines
    return [
        Option(
            id=new_id(),
            kind="route",
            storylineId=sls[i % len(sls)].id if sls else None,
            title=title,
            detail=detail,
            durationMinutes=min(minutes, max_minutes),
        )
        for i, (title, detail, minutes) in enumerate(DEFAULT_OPTIONS[meal])
    ]


def ensure_meals(plan: DayPlan, windows: list[dict]) -> list[str]:
    """Guarantee each meal window has a meal. Returns human-readable notes of what was added."""
    notes = []
    for w in windows:
        meal, lo, hi, pref = w["meal"], to_min(w["window_start"]), to_min(w["window_end"]), to_min(w["preferred"])
        has_meal = any(is_meal_chapter(c) and lo - 30 <= to_min(c.start) <= hi for c in plan.chapters)
        if has_meal:
            for c in plan.chapters:  # normalise: meal-ish chapters are meals
                if MEAL_RE.search(c.title or "") and c.source == "custom":
                    c.source = "meal"
            continue

        gaps = _free_gaps(plan.chapters, lo, hi)
        if gaps:
            # The free slot closest to the preferred time.
            a, b = min(gaps, key=lambda g: 0 if g[0] <= pref <= g[1] else min(abs(g[0] - pref), abs(g[1] - pref)))
            dur = min(DURATION[meal], b - a)
            start = min(max(pref, a), b - dur)
            plan.chapters.append(
                Chapter(
                    id=new_id(),
                    start=to_hm(start),
                    end=to_hm(start + dur),
                    title=meal.capitalize(),
                    priority="high",
                    source="meal",
                    options=_options(meal, plan, dur),
                )
            )
            notes.append(f"added {meal} at {to_hm(start)}")
            continue

        # Packed solid: offer eating as a path in the block that overlaps mealtime.
        overlapping = [c for c in plan.chapters if to_min(c.start) < hi and to_min(c.end) > lo]
        target = min(overlapping, key=lambda c: abs(to_min(c.start) - pref), default=None)
        if target:
            target.options.append(
                Option(
                    id=new_id(),
                    kind="route",
                    title=f"Take your {meal} break here",
                    detail=f"Your day is packed through {meal}time - this path swaps this block for a proper {meal}.",
                    durationMinutes=min(DURATION[meal], to_min(target.end) - to_min(target.start)),
                )
            )
            notes.append(f"offered {meal} inside '{target.title}' (no free time)")
    plan.chapters.sort(key=lambda c: c.start)
    return notes


def hm_valid(v: str) -> bool:
    try:
        datetime.strptime(v, "%H:%M")
        return True
    except ValueError:
        return False
