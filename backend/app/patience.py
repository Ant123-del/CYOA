"""Patience: the currency of hope.

Only what actually happens in the app is recorded:

- Emission (gaining patience) comes from fulfilling wants and needs: sleep (+5 an hour),
  eating (+2), taking a break (+1), anything tagged as a want or need.
- Absorption (losing patience) comes from what you push through: routines, school, work,
  anything on the to-do list, checking the app (-1 a visit), revising a plan with the AI
  (-1 each time), sleep you missed (-10 for
  every hour short of your goal), and going past the climax of a want or need.

Wants and needs follow a negative parabola: the patience climbs to a peak at the ideal
amount (the climax), falls back to 0 after a stretch, and past that you lose patience
because you got accustomed to the luxury. Eating has a wide stretch; addictive things
have a tight one.

Tasks get a check-in before (how much will this cost or give you?) and after (how much
did it?). The default is the average of your past scores for that activity.

The balance can go negative. Debt keeps compounding at `patienceInterestPerHour` % an
hour until it's paid back with emission.

Storage:
    users/{uid}/private/patience   {balance, startedAt, lastAccruedAt, lastOpenAt}
    users/{uid}/patience/{id}      ledger entries (PatienceEntry)

Entries that are recomputed or accumulated have stable ids (start, open_<date>,
interest_<date>, sleep_<night>, task_<date>_<chapterId>), so the balance only ever
moves by the difference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .firebase import db, user_ref
from .models import (
    Chapter,
    DayPlan,
    Option,
    PatienceEntry,
    PatienceSummary,
    PatienceSuggestion,
    TagPatience,
    UserSettings,
)
from .sleep import MAIN_SLEEP_MIN_HOURS, parse_iso, recent_sessions, to_iso
from .timeutil import minutes_between, new_id, tz

STARTING_BALANCE = 25.0
OPEN_COST = 1.0
OPEN_COOLDOWN = timedelta(minutes=15)  # one "check" of the app, however many refreshes
REVISION_COST = 1.0  # each Revise with AI
SLEEP_PER_HOUR = 5.0
SLEEP_DEBT_PER_HOUR = 10.0
FALLBACK_TASK = -2.0  # an unknown task, before there's any history to average
PARABOLA_FLOOR = 3  # never lose more than 3x the peak on one want/need

# Built-in wants & needs for chapters the planner makes.
NEEDS: dict[str, TagPatience] = {
    "meal": TagPatience(mode="parabola", points=2, idealMinutes=30, widthMinutes=60),
    "break": TagPatience(mode="parabola", points=1, idealMinutes=15, widthMinutes=30),
}


def _state_ref(uid: str):
    return user_ref(uid).collection("private").document("patience")


def _col(uid: str):
    return user_ref(uid).collection("patience")


def _kind(amount: float) -> str:
    return "emission" if amount >= 0 else "absorption"


def parabola(profile: TagPatience, minutes: float | None) -> float:
    """Patience for spending `minutes` on a want or need."""
    if profile.mode != "parabola":
        return profile.points
    m = profile.idealMinutes if minutes is None else max(0.0, minutes)
    peak, ideal, width = profile.points, profile.idealMinutes, profile.widthMinutes
    if m <= ideal:
        value = peak * (1 - ((ideal - m) / ideal) ** 2)  # climbing to the climax
    else:
        value = peak * (1 - ((m - ideal) / width) ** 2)  # accustomed to the luxury
    return round(max(value, -PARABOLA_FLOOR * abs(peak)), 1)


# ---------- transactions ----------


@dataclass
class _Ctx:
    now: datetime
    today: str
    state: dict
    read: Callable[[str], dict | None]
    writes: dict[str, dict | None] = field(default_factory=dict)
    delta: float = 0.0

    def put(self, eid: str, data: dict) -> None:
        old = self.read(eid)
        data = {**data, "id": eid, "amount": round(float(data["amount"]), 2)}
        data["kind"] = _kind(data["amount"])
        self.delta += data["amount"] - (old or {}).get("amount", 0.0)
        self.writes[eid] = data

    def delete(self, eid: str) -> None:
        old = self.read(eid)
        if old:
            self.delta -= old.get("amount", 0.0)
            self.writes[eid] = None


def _transact(uid: str, settings: UserSettings, mutate: Callable[[_Ctx], None] | None = None) -> None:
    """Run `mutate` against the ledger atomically, after starting the account (25 credits)
    if needed and charging interest on any debt since the last time."""
    sref, col = _state_ref(uid), _col(uid)
    zone = tz(settings.timezone)

    @firestore.transactional
    def run(tx):
        now = datetime.now(UTC)
        today = now.astimezone(zone).date().isoformat()
        snap = sref.get(transaction=tx)
        cache: dict[str, dict | None] = {}

        def read(eid: str) -> dict | None:
            if eid in ctx.writes:
                return ctx.writes[eid]
            if eid not in cache:
                s = col.document(eid).get(transaction=tx)
                cache[eid] = s.to_dict() if s.exists else None
            return cache[eid]

        state = snap.to_dict() if snap.exists else None
        ctx = _Ctx(now=now, today=today, state=state or {}, read=read)
        stamp = True
        if state is None:
            ctx.state = {"balance": 0.0, "startedAt": to_iso(now), "lastAccruedAt": to_iso(now), "lastOpenAt": None}
            ctx.put("start", {"at": to_iso(now), "date": today, "amount": STARTING_BALANCE, "source": "start", "label": "Starting balance"})
        else:
            stamp = _accrue(ctx, settings)
        if mutate:
            mutate(ctx)

        for eid, data in ctx.writes.items():
            if data is None:
                tx.delete(col.document(eid))
            else:
                tx.set(col.document(eid), PatienceEntry(**data).model_dump())
        before = ctx.state.get("balance", 0.0)
        ctx.state["balance"] = round(before + ctx.delta, 4)
        # Keep the old stamp while unbilled interest is still too small to show, unless
        # the debt itself changed (then interest starts fresh on the new amount).
        if stamp or ctx.delta:
            ctx.state["lastAccruedAt"] = to_iso(now)
        tx.set(sref, ctx.state)

    run(db().transaction())


def _accrue(ctx: _Ctx, settings: UserSettings) -> bool:
    """Compound interest on a negative balance since it was last charged. Returns False
    when there is interest owed but too little to bill yet (so the clock isn't reset)."""
    balance = ctx.state.get("balance", 0.0)
    rate = max(0.0, settings.patienceInterestPerHour) / 100
    last = ctx.state.get("lastAccruedAt")
    if balance >= 0 or rate == 0 or not last:
        return True
    hours = (ctx.now - parse_iso(last)).total_seconds() / 3600
    interest = balance * ((1 + rate) ** hours - 1)
    if abs(interest) < 0.01:
        return False
    eid = f"interest_{ctx.today}"
    old = ctx.read(eid) or {}
    ctx.put(
        eid,
        {
            "at": to_iso(ctx.now),
            "date": ctx.today,
            "amount": old.get("amount", 0.0) + interest,
            "source": "interest",
            "label": f"Interest on debt ({settings.patienceInterestPerHour:g}% an hour)",
        },
    )
    return True


# ---------- what the app records ----------


def check_app(uid: str, settings: UserSettings) -> None:
    """Opening (or coming back to) the app costs a point - once per OPEN_COOLDOWN."""

    def mutate(ctx: _Ctx):
        last = ctx.state.get("lastOpenAt")
        if last and ctx.now - parse_iso(last) < OPEN_COOLDOWN:
            return
        eid = f"open_{ctx.today}"
        count = (ctx.read(eid) or {}).get("count", 0) + 1
        ctx.put(
            eid,
            {
                "at": to_iso(ctx.now),
                "date": ctx.today,
                "amount": -OPEN_COST * count,
                "source": "open",
                "label": "Checked the app" if count == 1 else f"Checked the app ×{count}",
                "count": count,
            },
        )
        ctx.state["lastOpenAt"] = to_iso(ctx.now)

    _transact(uid, settings, mutate)


def charge_revision(uid: str, settings: UserSettings) -> None:
    """Every revision of a plan (Revise with AI) costs a point."""

    def mutate(ctx: _Ctx):
        eid = f"revise_{ctx.today}"
        count = (ctx.read(eid) or {}).get("count", 0) + 1
        ctx.put(
            eid,
            {
                "at": to_iso(ctx.now),
                "date": ctx.today,
                "amount": -REVISION_COST * count,
                "source": "revise",
                "label": "Revised a plan" if count == 1 else f"Revised a plan ×{count}",
                "count": count,
            },
        )

    _transact(uid, settings, mutate)


def sync_sleep(uid: str, settings: UserSettings) -> None:
    """One entry per night (keyed by the local date you woke up): +5 an hour slept, and
    -10 for each hour short of the sleep goal. Only sleep that ended after the account
    started counts. Recomputed whenever sleep changes, so edits and deletes are refunded."""
    state = _state_ref(uid).get()
    if not state.exists:
        _transact(uid, settings)
        state = _state_ref(uid).get()
    started = parse_iso(state.to_dict()["startedAt"])
    zone = tz(settings.timezone)
    sessions = [s for s in recent_sessions(uid) if s.end and parse_iso(s.end) >= started]

    nights: dict[str, dict] = {}
    for s in sessions:
        end = parse_iso(s.end)
        hours = (end - parse_iso(s.start)).total_seconds() / 3600
        n = nights.setdefault(end.astimezone(zone).date().isoformat(), {"hours": 0.0, "main": False, "at": s.end})
        n["hours"] += hours
        n["main"] = n["main"] or hours >= MAIN_SLEEP_MIN_HOURS
        n["at"] = max(n["at"], s.end)

    window_start = (datetime.now(UTC) - timedelta(days=20)).astimezone(zone).date().isoformat()
    existing = [
        d.id
        for d in _col(uid).where(filter=FieldFilter("source", "==", "sleep")).stream()
        if (d.to_dict() or {}).get("date", "") >= window_start
    ]
    target = settings.sleepTargetHours

    def mutate(ctx: _Ctx):
        for night, n in nights.items():
            hours = round(n["hours"], 2)
            short = max(0.0, target - hours) if n["main"] else 0.0
            amount = round(SLEEP_PER_HOUR * hours - SLEEP_DEBT_PER_HOUR * short, 1)
            label = f"Slept {hours:g}h" + (f" · {short:g}h short of {target:g}h" if short else "")
            eid = f"sleep_{night}"
            old = ctx.read(eid)
            if old and old.get("amount") == amount and old.get("label") == label:
                continue
            ctx.put(eid, {"at": n["at"], "date": night, "amount": amount, "source": "sleep", "label": label, "minutes": round(hours * 60)})
        for eid in existing:
            if eid.removeprefix("sleep_") not in nights:
                ctx.delete(eid)  # the sleep was deleted

    _transact(uid, settings, mutate)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def activity_key(chapter: Chapter, option: Option) -> str:
    """What counts as "the same activity" when averaging past scores."""
    if chapter.source in NEEDS:
        return chapter.source
    if len(option.goalIds) == 1:
        return f"goal:{option.goalIds[0]}"
    return f"title:{_norm(option.title)}"


def _task_tags(uid: str, option: Option) -> list[str]:
    tags: list[str] = []
    for gid in option.goalIds:
        snap = user_ref(uid).collection("goals").document(gid).get()
        for t in (snap.to_dict() or {}).get("tags", []) if snap.exists else []:
            if t not in tags:
                tags.append(t)
    return tags


def suggest(uid: str, settings: UserSettings, chapter: Chapter, option: Option, minutes: int | None = None) -> PatienceSuggestion:
    """The default for a check-in.

    1. A want or need (a parabola tag, or a meal / break): the parabola at this duration.
    2. Your past scores for this same activity: their average.
    3. A fixed tag default from the Board.
    4. The average of all your task scores.
    5. -2.
    """
    minutes = minutes if minutes is not None else option.durationMinutes or minutes_between(chapter.start, chapter.end)
    tags = _task_tags(uid, option)
    configured = [settings.patienceTags[t] for t in tags if t in settings.patienceTags]
    base = {"minutes": minutes, "label": option.title, "tags": tags}

    curves = [p for p in configured if p.mode == "parabola"] or ([NEEDS[chapter.source]] if chapter.source in NEEDS else [])
    if curves:
        value = sum(parabola(p, minutes) for p in curves) / len(curves)
        return PatienceSuggestion(amount=round(value, 1), basis="tag" if configured else "need", profile=curves[0], **base)

    key = activity_key(chapter, option)
    scored = [
        e.to_dict()
        for e in _col(uid).where(filter=FieldFilter("source", "==", "task")).stream()
        if (e.to_dict() or {}).get("actual") is not None
    ]
    same = [e["actual"] for e in scored if e.get("activityKey") == key]
    if same:
        return PatienceSuggestion(amount=round(sum(same) / len(same), 1), basis="history", samples=len(same), **base)
    if configured:
        return PatienceSuggestion(amount=round(sum(p.points for p in configured) / len(configured), 1), basis="tag", **base)
    others = [e["actual"] for e in scored if e.get("activityKey") not in NEEDS]
    if others:
        return PatienceSuggestion(amount=round(sum(others) / len(others), 1), basis="average", samples=len(others), **base)
    return PatienceSuggestion(amount=FALLBACK_TASK, basis="fallback", **base)


def record_task(
    uid: str, settings: UserSettings, plan: DayPlan, chapter: Chapter, option: Option, phase: str, amount: float, minutes: int | None
) -> None:
    """Before: what you expect it to cost / give (counts right away). After: what it
    actually did (replaces the expectation)."""
    eid = f"task_{plan.date}_{chapter.id}"
    tags = _task_tags(uid, option)

    def mutate(ctx: _Ctx):
        old = ctx.read(eid) or {}
        same_option = old.get("optionId") == option.id
        data = {
            "at": old.get("at") or to_iso(ctx.now),
            "date": plan.date,
            "source": "task",
            "label": option.title,
            "tags": tags,
            "activityKey": activity_key(chapter, option),
            "chapterId": chapter.id,
            "optionId": option.id,
            "minutes": minutes if minutes is not None else old.get("minutes") if same_option else None,
            "expected": old.get("expected") if same_option else None,
            "actual": None,
            "settled": False,
        }
        if phase == "before":
            data.update(expected=amount, amount=amount)
        else:
            data.update(actual=amount, amount=amount, settled=True)
        ctx.put(eid, data)

    _transact(uid, settings, mutate)


def remove_task(uid: str, settings: UserSettings, date: str, chapter_id: str) -> None:
    """Changing course on a task refunds what it was recorded at."""
    eid = f"task_{date}_{chapter_id}"
    if _col(uid).document(eid).get().exists:
        _transact(uid, settings, lambda ctx: ctx.delete(eid))


def log_entry(uid: str, settings: UserSettings, label: str, amount: float, tags: list[str], minutes: int | None) -> None:
    """Something you did that wasn't a planned chapter (a snack, a walk, an hour of TV)."""
    eid = new_id()

    def mutate(ctx: _Ctx):
        ctx.put(eid, {"at": to_iso(ctx.now), "date": ctx.today, "amount": amount, "source": "log", "label": label, "tags": tags, "minutes": minutes})

    _transact(uid, settings, mutate)


def delete_entry(uid: str, settings: UserSettings, eid: str) -> bool:
    snap = _col(uid).document(eid).get()
    if not snap.exists or (snap.to_dict() or {}).get("source") not in ("log", "task"):
        return False
    _transact(uid, settings, lambda ctx: ctx.delete(eid))
    return True


def summary(uid: str, settings: UserSettings, limit: int = 60) -> PatienceSummary:
    _transact(uid, settings)  # starts the account and charges interest up to now
    state = _state_ref(uid).get().to_dict()
    today = datetime.now(UTC).astimezone(tz(settings.timezone)).date().isoformat()
    col = _col(uid)
    recent = [PatienceEntry(**d.to_dict()) for d in col.order_by("at", direction=firestore.Query.DESCENDING).limit(limit).stream()]
    todays = [PatienceEntry(**d.to_dict()) for d in col.where(filter=FieldFilter("date", "==", today)).stream()]
    unsettled = sum(1 for _ in col.where(filter=FieldFilter("settled", "==", False)).stream())
    return PatienceSummary(
        balance=round(state["balance"], 2),
        startedAt=state["startedAt"],
        interestPerHour=settings.patienceInterestPerHour,
        emittedToday=round(sum(e.amount for e in todays if e.amount > 0), 1),
        absorbedToday=round(sum(e.amount for e in todays if e.amount < 0), 1),
        unsettled=unsettled,
        entries=recent,
    )
