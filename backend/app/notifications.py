"""Reminder emails: "it's time to choose your next chapter".

Each unchosen chapter gets a document in the top-level `reminders` collection
with a UTC `sendAt`. A background job checks every minute, emails the user, and
deletes the reminder. Choosing an option (or editing the day) removes/rebuilds them.
"""

import html
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from google.cloud.firestore_v1.base_query import FieldFilter

from .auth import load_settings_by_uid
from .config import get_settings
from .firebase import db, user_ref
from .models import Chapter, DayPlan, UserSettings
from .timeutil import local_dt

log = logging.getLogger("cyoa.notify")

KIND_LABELS = {"yes": "Yes", "yes_and": "Yes, and…", "no": "No", "no_and": "No, and…", "route": "Route"}


def _reminder_id(uid: str, day: str, chapter_id: str) -> str:
    return f"{uid}_{day}_{chapter_id}"


def rebuild_reminders(uid: str, plan: DayPlan, settings: UserSettings) -> None:
    col = db().collection("reminders")
    existing = col.where(filter=FieldFilter("uid", "==", uid)).where(filter=FieldFilter("date", "==", plan.date)).stream()
    batch = db().batch()
    for doc in existing:
        batch.delete(doc.reference)
    if settings.emailReminders:
        now = datetime.now(UTC)
        for ch in plan.chapters:
            if ch.chosenOptionId or not ch.options or ch.source == "break":
                continue  # (breaks are short - no email for them)
            send_at = local_dt(plan.date, ch.start, settings.timezone) - timedelta(minutes=settings.reminderLeadMinutes)
            if send_at.astimezone(UTC) < now - timedelta(minutes=1):
                continue
            batch.set(
                col.document(_reminder_id(uid, plan.date, ch.id)),
                {"uid": uid, "date": plan.date, "chapterId": ch.id, "sendAt": send_at.astimezone(UTC)},
            )
    batch.commit()


def clear_reminder(uid: str, day: str, chapter_id: str) -> None:
    db().collection("reminders").document(_reminder_id(uid, day, chapter_id)).delete()


# ---------- email ----------


def send_email(to: str, subject: str, html_body: str, text_body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        log.info("[email not configured] To: %s | %s\n%s", to, subject, text_body)
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
        if s.smtp_use_tls:
            server.starttls()
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)


def chapter_email(plan: DayPlan, ch: Chapter) -> tuple[str, str, str]:
    link = f"{get_settings().app_url}/today?date={plan.date}&chapter={ch.id}"
    storyline_names = {s.id: s.name for s in plan.storylines}
    subject = f"⚔️ Choose your path: {ch.title} ({ch.start})"
    rows_html, rows_text = [], []
    for o in ch.options:
        tag = KIND_LABELS.get(o.kind, "Route")
        if o.kind == "route" and o.storylineId in storyline_names:
            tag = storyline_names[o.storylineId]
        rows_html.append(
            f"<li style='margin:8px 0'><b>{html.escape(tag)}:</b> {html.escape(o.title)}"
            f"<br><span style='color:#666'>{html.escape(o.detail)}</span></li>"
        )
        rows_text.append(f"- {tag}: {o.title} — {o.detail}")
    html_body = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:auto">
      <h2 style="margin-bottom:4px">A new chapter begins at {ch.start}</h2>
      <p style="color:#555;margin-top:0">{html.escape(ch.title)}</p>
      <ul style="padding-left:18px">{''.join(rows_html)}</ul>
      <p><a href="{link}" style="background:#7c5cff;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none">Choose your path</a></p>
      <p style="color:#999;font-size:12px">CYOA — Choose Your Own Adventure</p>
    </div>"""
    text_body = f"A new chapter begins at {ch.start}: {ch.title}\n\n" + "\n".join(rows_text) + f"\n\nChoose: {link}"
    return subject, html_body, text_body


def process_due_reminders() -> int:
    """Send every reminder whose time has come. Returns number sent."""
    now = datetime.now(UTC)
    sent = 0
    docs = db().collection("reminders").where(filter=FieldFilter("sendAt", "<=", now)).limit(100).stream()
    for doc in docs:
        r = doc.to_dict() or {}
        try:
            uid, day, chapter_id = r["uid"], r["date"], r["chapterId"]
            settings = load_settings_by_uid(uid)
            snap = user_ref(uid).collection("days").document(day).get()
            if settings and settings.emailReminders and snap.exists:
                plan = DayPlan(**snap.to_dict())
                ch = next((c for c in plan.chapters if c.id == chapter_id), None)
                stale = now - r["sendAt"] > timedelta(hours=1)  # e.g. server was off
                if ch and not ch.chosenOptionId and not stale:
                    to = settings.notifyEmail or settings.email
                    if to:
                        send_email(to, *chapter_email(plan, ch))
                        sent += 1
        except Exception:
            log.exception("Failed to process reminder %s", doc.id)
        finally:
            doc.reference.delete()
    return sent
