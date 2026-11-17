import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def parse_hm(hm: str) -> time:
    h, m = hm.split(":")[:2]
    return time(int(h) % 24, int(m))


def local_dt(day: str, hm: str, tz_name: str) -> datetime:
    """Combine YYYY-MM-DD + HH:MM in the user's timezone into an aware datetime."""
    return datetime.combine(date.fromisoformat(day), parse_hm(hm), tzinfo=tz(tz_name))


def day_bounds(day: str, tz_name: str) -> tuple[datetime, datetime]:
    start = datetime.combine(date.fromisoformat(day), time(0, 0), tzinfo=tz(tz_name))
    return start, start + timedelta(days=1)


def minutes_between(start_hm: str, end_hm: str) -> int:
    s, e = parse_hm(start_hm), parse_hm(end_hm)
    diff = (e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)
    return diff if diff > 0 else 30
