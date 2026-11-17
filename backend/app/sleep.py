"""Sleep tracking: sessions, sleep debt, and a suggested bedtime.

Each session is a doc in users/{uid}/sleep with UTC ISO `start` and `end`
(`end` is None while the user is asleep). Everything the UI and the AI need
is derived from the last few weeks of sessions by `sleep_summary`.
"""

from datetime import UTC, date, datetime, timedelta
from statistics import median

from google.cloud.firestore_v1.base_query import FieldFilter

from .firebase import user_ref
from .models import SleepSession, SleepSummary
from .timeutil import tz

HISTORY_DAYS = 21
DEBT_WINDOW_DAYS = 7
MAIN_SLEEP_MIN_HOURS = 3  # shorter sessions are naps: they count toward totals, not toward "typical" times
MAX_SESSION_HOURS = 36
DEFAULT_WAKE = "07:30"
WIND_DOWN_MINUTES = 30


def to_iso(dt: datetime) -> str:
    """Uniform UTC ISO strings so they sort and compare correctly as text."""
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def sleep_col(uid: str):
    return user_ref(uid).collection("sleep")


def recent_sessions(uid: str, days: int = HISTORY_DAYS) -> list[SleepSession]:
    since = to_iso(datetime.now(UTC) - timedelta(days=days))
    snaps = sleep_col(uid).where(filter=FieldFilter("start", ">=", since)).stream()
    return sorted((SleepSession(**s.to_dict()) for s in snaps), key=lambda s: s.start)


def _hours(s: SleepSession) -> float:
    return (parse_iso(s.end) - parse_iso(s.start)).total_seconds() / 3600 if s.end else 0.0


def _hm(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _minutes(hm: str) -> int:
    h, m = hm.split(":")[:2]
    return int(h) * 60 + int(m)


def _typical(times: list[datetime], tz_name: str, pivot_hour: int) -> str | None:
    """Median local clock time. `pivot_hour` is where the 24h clock is "cut" so that
    times on both sides of midnight average sensibly (noon for bedtimes)."""
    if not times:
        return None
    pivot = pivot_hour * 60
    shifted = [((t.astimezone(tz(tz_name)).hour * 60 + t.astimezone(tz(tz_name)).minute) - pivot) % 1440 for t in times]
    return _hm(median(shifted) + pivot)


def sleep_summary(
    sessions: list[SleepSession],
    *,
    tz_name: str,
    target_hours: float,
    tomorrow_wake: str | None = None,
    now: datetime | None = None,
) -> SleepSummary:
    now = now or datetime.now(UTC)
    zone = tz(tz_name)
    open_session = next((s for s in reversed(sessions) if not s.end), None)
    done = [s for s in sessions if s.end]
    main = [s for s in done if _hours(s) >= MAIN_SLEEP_MIN_HOURS]

    # Sleep per night, keyed by the local date you woke up on (naps fold into that day).
    by_night: dict[date, float] = {}
    for s in done:
        night = parse_iso(s.end).astimezone(zone).date()
        by_night[night] = by_night.get(night, 0.0) + _hours(s)

    today = now.astimezone(zone).date()
    window = [d for d in by_night if (today - d).days < DEBT_WINDOW_DAYS]
    # Surplus nights pay back short ones; untracked nights count as neither.
    debt = max(0.0, sum(target_hours - by_night[d] for d in window))
    avg = sum(by_night[d] for d in window) / len(window) if window else None

    last = done[-1] if done else None
    last_main = main[-1] if main else None
    since_24h = now - timedelta(hours=24)
    slept_24h = sum(
        max(0.0, (min(parse_iso(s.end), now) - max(parse_iso(s.start), since_24h)).total_seconds() / 3600) for s in done
    )
    awake_hours = None
    if not open_session and last:
        awake_hours = (now - parse_iso(last.end)).total_seconds() / 3600

    # "Last night" = the most recent main sleep (plus naps that day), if it was recent enough to matter.
    last_night = None
    if last_main and now - parse_iso(last_main.end) < timedelta(hours=36):
        woke_on = parse_iso(last_main.end).astimezone(zone).date()
        last_night = by_night.get(woke_on, _hours(last_main))

    # How tired: the worse of last night and the running weekly debt, plus long stretches awake.
    status = "unknown"
    if last_night is not None:
        short = target_hours - last_night
        if short >= 2 or debt >= 6 or (awake_hours or 0) >= 20:
            status = "deprived"
        elif short >= 1 or debt >= 3 or (awake_hours or 0) >= 17:
            status = "low"
        else:
            status = "rested"

    typical_bed = _typical([parse_iso(s.start) for s in main[-14:]], tz_name, pivot_hour=12)
    typical_wake = _typical([parse_iso(s.end) for s in main[-14:]], tz_name, pivot_hour=18)

    # Bedtime = when you need to be up, minus your target, minus a little extra while in debt
    # (15 min per hour owed, at most an hour - catching up slowly beats one huge lie-in).
    wake_anchor = tomorrow_wake or typical_wake or DEFAULT_WAKE
    recovery = min(60, int(debt * 15) // 15 * 15)
    bed_minutes = _minutes(wake_anchor) - target_hours * 60 - recovery
    suggested_bed = _hm(bed_minutes)

    return SleepSummary(
        asleep=open_session is not None,
        sleepingSince=open_session.start if open_session else None,
        sessionId=open_session.id if open_session else None,
        targetHours=target_hours,
        status=status,
        lastSleepHours=round(last_night, 2) if last_night is not None else None,
        lastWokeAt=last.end if last else None,
        hoursAwake=round(awake_hours, 2) if awake_hours is not None else None,
        sleptLast24h=round(slept_24h, 2),
        avgHours7d=round(avg, 2) if avg is not None else None,
        debtHours=round(debt, 2),
        nightsTracked=len(window),
        typicalBedtime=typical_bed,
        typicalWake=typical_wake,
        wakeAnchor=wake_anchor,
        suggestedBedtime=suggested_bed,
        windDownAt=_hm(bed_minutes - WIND_DOWN_MINUTES),
        sessions=list(reversed(done[-14:])),
    )


def ai_context(summary: SleepSummary, tz_name: str) -> dict:
    """What the planner sees: compact, local times, no raw session list."""

    def local(iso: str | None) -> str | None:
        return parse_iso(iso).astimezone(tz(tz_name)).strftime("%Y-%m-%d %H:%M") if iso else None

    if summary.status == "unknown" and not summary.asleep:
        return {"tracked": False}
    return {
        "tracked": True,
        "status": summary.status,
        "target_hours": summary.targetHours,
        "last_sleep_hours": summary.lastSleepHours,
        "slept_last_24h": summary.sleptLast24h,
        "avg_hours_last_7_nights": summary.avgHours7d,
        "sleep_debt_hours_7d": summary.debtHours,
        "woke_at_local": local(summary.lastWokeAt),
        "hours_awake_now": summary.hoursAwake,
        "currently_asleep": summary.asleep,
        "typical_bedtime": summary.typicalBedtime,
        "typical_wake": summary.typicalWake,
        "suggested_bedtime": summary.suggestedBedtime,
        "wind_down_at": summary.windDownAt,
    }
