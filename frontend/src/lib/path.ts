/**
 * Where someone is in a branching day (mirrors backend/app/path.py - keep them in step).
 *
 * A day can have several timelines (versions of the same day). You're always on one.
 * Choosing an option may move you to another (option.nextTimelineId). Activities shared by
 * timelines (same activityId) count as done everywhere once done anywhere, so switching
 * never repeats them.
 */
import type { Chapter, DayPlan, Timeline } from '../types'

export const activity = (c: Chapter) => c.activityId || c.id

export const hasTimelines = (plan: DayPlan) => Boolean(plan.timelines?.length)

export function currentTimeline(plan: DayPlan): Timeline | null {
  const tls = plan.timelines ?? []
  return tls.find((t) => t.id === plan.currentTimelineId) ?? tls[0] ?? null
}

export function doneActivities(plan: DayPlan): Set<string> {
  return new Set(plan.chapters.filter((c) => c.chosenOptionId).map(activity))
}

/** Latest end time of anything chosen - the path continues from there. */
export function cutoff(plan: DayPlan): string {
  const ends = plan.chapters.filter((c) => c.chosenOptionId).map((c) => c.end)
  return ends.length ? ends.sort().at(-1)! : '00:00'
}

/** Chapters still ahead on your current path, in time order. */
export function upcoming(plan: DayPlan): Chapter[] {
  const done = doneActivities(plan)
  const tl = currentTimeline(plan)
  const cut = tl ? cutoff(plan) : '00:00'
  return plan.chapters
    .filter((c) => !c.chosenOptionId && !done.has(activity(c)) && (!tl || (c.timelineId === tl.id && c.start >= cut)))
    .sort((a, b) => a.start.localeCompare(b.start))
}

/** Your day as lived so far plus what's ahead: chosen chapters (any timeline) + upcoming. */
export function pathChapters(plan: DayPlan): Chapter[] {
  if (!hasTimelines(plan)) return plan.chapters
  const chosen = plan.chapters.filter((c) => c.chosenOptionId)
  return [...chosen, ...upcoming(plan)].sort((a, b) => a.start.localeCompare(b.start))
}

export function timelineById(plan: DayPlan, id?: string | null): Timeline | undefined {
  return plan.timelines?.find((t) => t.id === id)
}
