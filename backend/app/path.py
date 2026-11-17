"""Where someone is in a branching day.

A day can have several timelines (versions of the same day). The person is always on one
(`currentTimelineId`). Choosing an option may move them to another timeline
(`Option.nextTimelineId`). Activities shared between timelines (same `activityId`) count as
done everywhere once done anywhere, so switching never repeats them.

The frontend mirrors this logic in src/lib/path.ts - keep them in step.
"""

from .models import Chapter, DayPlan


def activity(c: Chapter) -> str:
    return c.activityId or c.id


def current_timeline(plan: DayPlan) -> str | None:
    ids = [t.id for t in plan.timelines]
    if not ids:
        return None
    return plan.currentTimelineId if plan.currentTimelineId in ids else ids[0]


def done_activities(plan: DayPlan) -> set[str]:
    return {activity(c) for c in plan.chapters if c.chosenOptionId}


def upcoming(plan: DayPlan) -> list[Chapter]:
    """Chapters still ahead on the person's current path, in time order."""
    done = done_activities(plan)
    tl = current_timeline(plan)
    chosen_ends = [c.end for c in plan.chapters if c.chosenOptionId]
    cutoff = max(chosen_ends) if (chosen_ends and tl) else "00:00"
    return sorted(
        (
            c
            for c in plan.chapters
            if not c.chosenOptionId
            and activity(c) not in done
            and (tl is None or c.timelineId == tl)
            and (tl is None or c.start >= cutoff)
        ),
        key=lambda c: c.start,
    )


def visited_timelines(plan: DayPlan) -> set[str]:
    tl = current_timeline(plan)
    return {c.timelineId for c in plan.chapters if c.chosenOptionId and c.timelineId} | ({tl} if tl else set())
