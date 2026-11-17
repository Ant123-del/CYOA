"""Long-term AI memory: what the planner knows about a person, built up over time.

Three sources feed every AI call:
  * notes   - durable facts/preferences. Some the user writes ("source": "user"),
              most the AI learns from requests and choices ("source": "ai").
  * log     - a rolling list of what the user asked for (priorities, hints).
  * history - the user's recent saved days: which paths they actually took,
              which storylines they favour, which chapters they left untouched.

Stored at users/{uid}/private/aiMemory (server-side only, like the calendar link).
"""

import logging
from collections import Counter
from datetime import date as date_cls
from datetime import timedelta

from google.cloud.firestore_v1.base_query import FieldFilter

from .firebase import db, user_ref
from .timeutil import new_id, now_iso

log = logging.getLogger("cyoa.memory")

MAX_AI_NOTES = 40
MAX_USER_NOTES = 40
MAX_LOG = 40
NOTE_MAX_CHARS = 280
HISTORY_DAYS = 14


def _ref(uid: str):
    return user_ref(uid).collection("private").document("aiMemory")


def load(uid: str) -> dict:
    snap = _ref(uid).get()
    data = snap.to_dict() if snap.exists else {}
    return {"notes": list(data.get("notes", [])), "log": list(data.get("log", []))}


def _save(uid: str, mem: dict) -> None:
    _ref(uid).set({"notes": mem["notes"], "log": mem["log"][-MAX_LOG:], "updatedAt": now_iso()})


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:NOTE_MAX_CHARS]


def _cap_notes(notes: list[dict]) -> list[dict]:
    """Keep the newest notes of each kind within their caps (user notes are never evicted by AI notes)."""
    user = [n for n in notes if n.get("source") == "user"][-MAX_USER_NOTES:]
    ai = [n for n in notes if n.get("source") != "user"][-MAX_AI_NOTES:]
    keep = {id(n) for n in user + ai}
    return [n for n in notes if id(n) in keep]


# ---------- user-facing edits ----------


def add_note(uid: str, text: str, source: str = "user") -> dict:
    mem = load(uid)
    text = _clean(text)
    if text:
        mem["notes"].append({"id": new_id(), "text": text, "source": source, "createdAt": now_iso()})
        mem["notes"] = _cap_notes(mem["notes"])
        _save(uid, mem)
    return mem


def delete_note(uid: str, note_id: str) -> dict:
    mem = load(uid)
    mem["notes"] = [n for n in mem["notes"] if n.get("id") != note_id]
    _save(uid, mem)
    return mem


def clear(uid: str) -> dict:
    _ref(uid).delete()
    return {"notes": [], "log": []}


# ---------- feeding the AI ----------


def _recent_days(uid: str, before: str) -> list[dict]:
    """Compact history of the last HISTORY_DAYS saved days strictly before `before`."""
    try:
        end = date_cls.fromisoformat(before) - timedelta(days=1)
    except ValueError:
        return []
    start = end - timedelta(days=HISTORY_DAYS - 1)
    snaps = (
        user_ref(uid)
        .collection("days")
        .where(filter=FieldFilter("date", ">=", start.isoformat()))
        .where(filter=FieldFilter("date", "<=", end.isoformat()))
        .stream()
    )
    out = []
    for snap in snaps:
        d = snap.to_dict() or {}
        names = {s["id"]: s.get("name", "") for s in d.get("storylines", [])}
        taken, untouched = [], []
        for c in d.get("chapters", []):
            opt = next((o for o in c.get("options", []) if o.get("id") == c.get("chosenOptionId")), None)
            if opt:
                taken.append(
                    {
                        "time": f"{c.get('start')}-{c.get('end')}",
                        "chapter": c.get("title", ""),
                        "chose": opt.get("title", ""),
                        "kind": opt.get("kind"),
                        "storyline": names.get(opt.get("storylineId"), ""),
                        "passed_on": [o.get("title", "") for o in c.get("options", []) if o is not opt][:3],
                    }
                )
            else:
                untouched.append(f"{c.get('start')} {c.get('title', '')}")
        out.append(
            {
                "date": d.get("date"),
                "weekday": date_cls.fromisoformat(d["date"]).strftime("%A") if d.get("date") else "",
                "priorities_they_gave": (d.get("priorities") or "")[:300],
                "storylines": list(names.values()),
                "paths_taken": taken,
                "chapters_never_chosen": untouched,
            }
        )
    return sorted(out, key=lambda x: x["date"] or "")


def _patterns(days: list[dict]) -> dict:
    storylines = Counter(t["storyline"] for d in days for t in d["paths_taken"] if t["storyline"])
    kinds = Counter(t["kind"] for d in days for t in d["paths_taken"])
    total = sum(len(d["paths_taken"]) + len(d["chapters_never_chosen"]) for d in days)
    chosen = sum(len(d["paths_taken"]) for d in days)
    return {
        "days_planned": len(days),
        "chapters_followed_through": f"{chosen}/{total}" if total else "0/0",
        "favourite_storylines": storylines.most_common(4),
        "calendar_choices": {k: v for k, v in kinds.items() if k != "route"},
    }


def context_for(uid: str, for_date: str) -> dict:
    """Everything the AI should know about this person before it plans."""
    try:
        mem = load(uid)
        days = _recent_days(uid, for_date)
    except Exception:
        log.exception("Memory load failed; planning without it")
        return {"first_time": True}
    if not mem["notes"] and not mem["log"] and not days:
        return {"first_time": True}
    return {
        "first_time": False,
        "what_you_know_about_them": [
            {"id": n["id"], "text": n["text"], "told_by": "them" if n.get("source") == "user" else "you"}
            for n in mem["notes"]
        ],
        "their_recent_requests": [
            {k: e[k] for k in ("at", "type", "date", "text") if k in e} for e in mem["log"][-15:]
        ],
        "recent_days": days,
        "patterns": _patterns(days),
    }


def record(uid: str, *, kind: str, day: str, text: str, learned: list[str], outdated_ids: list[str]) -> None:
    """Log a request and fold what the AI learned back into memory (transactionally)."""
    from google.cloud import firestore

    ref = _ref(uid)

    @firestore.transactional
    def _apply(tx):
        snap = ref.get(transaction=tx)
        data = snap.to_dict() if snap.exists else {}
        notes = list(data.get("notes", []))
        log_ = list(data.get("log", []))
        drop = set(outdated_ids)
        # The AI may retire its own notes, never ones the user wrote.
        notes = [n for n in notes if not (n.get("id") in drop and n.get("source") != "user")]
        existing = {n["text"].lower() for n in notes}
        for t in learned[:5]:
            t = _clean(t)
            if t and t.lower() not in existing:
                notes.append({"id": new_id(), "text": t, "source": "ai", "createdAt": now_iso()})
                existing.add(t.lower())
        if text.strip():
            log_.append({"at": now_iso(), "type": kind, "date": day, "text": _clean(text)})
        tx.set(ref, {"notes": _cap_notes(notes), "log": log_[-MAX_LOG:], "updatedAt": now_iso()})

    try:
        _apply(db().transaction())
    except Exception:
        log.exception("Memory update failed")
