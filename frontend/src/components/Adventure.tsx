import type { CSSProperties } from 'react'
import { KIND_LABEL, type Chapter, type Option, type Storyline, type Timeline } from '../types'

export const KIND_COLOR: Record<string, string> = {
  yes: 'var(--yes)',
  yes_and: 'var(--yes-and)',
  no: 'var(--no)',
  no_and: 'var(--no-and)',
}

export function optionColor(o: Option, storylines: Storyline[]): string {
  if (o.kind !== 'route') return KIND_COLOR[o.kind]
  return storylines.find((s) => s.id === o.storylineId)?.color ?? 'var(--accent)'
}

export function KindBadge({ option, storylines }: { option: Option; storylines: Storyline[] }) {
  const sl = storylines.find((s) => s.id === option.storylineId)
  const label = option.kind === 'route' ? sl?.name ?? 'Route' : KIND_LABEL[option.kind]
  return (
    <span className="kind-badge" style={{ '--c': optionColor(option, storylines) } as CSSProperties}>
      {label}
    </span>
  )
}

export function StorylineLegend({ storylines }: { storylines: Storyline[] }) {
  if (!storylines.length) return null
  return (
    <div className="legend">
      {storylines.map((s) => (
        <div key={s.id} className="legend-item" title={s.description}>
          <span className="dot" style={{ background: s.color ?? 'var(--accent)' }} />
          <span className="legend-name">{s.name}</span>
          {s.description && <span className="legend-desc">{s.description}</span>}
        </div>
      ))}
    </div>
  )
}

export function SourceTag({ chapter }: { chapter: Chapter }) {
  if (chapter.source === 'calendar') return <CalendarTag chapter={chapter} />
  if (chapter.source === 'meal') return <span className="tag meal-tag">🍽 Meal</span>
  if (chapter.source === 'break') return <span className="tag break-tag">☕ Break</span>
  return null
}

export function CalendarTag({ chapter }: { chapter: Chapter }) {
  return (
    <span className="tag cal-tag" title={chapter.calendarId ?? 'Google Calendar'}>
      <span className="dot" style={{ background: chapter.calendarColor ?? 'var(--accent)' }} />
      {chapter.calendarName ?? '📅 calendar'}
    </span>
  )
}

/** "→ Ease in" - the timeline an option leads to (nothing when it stays). */
export function SwitchTag({ option, timelines }: { option: Option; timelines?: Timeline[] }) {
  const to = option.nextTimelineId ? timelines?.find((t) => t.id === option.nextTimelineId) : undefined
  if (!to) return null
  return (
    <span className="switch-tag" style={{ '--c': to.color ?? 'var(--accent)' } as CSSProperties} title={to.description}>
      → {timelineLabel(to)}
    </span>
  )
}

export function TimelineBadge({ timeline }: { timeline?: Timeline | null }) {
  if (!timeline) return null
  return (
    <span
      className="timeline-badge"
      style={{ '--c': timeline.color ?? 'var(--accent)' } as CSSProperties}
      title={timeline.role ? ROLE_LABEL[timeline.role] : undefined}
    >
      {timelineLabel(timeline)}
    </span>
  )
}

export const ROLE_ICON: Record<string, string> = { healthy: '🌱', recovery: '🔋', rebel: '🎈' }
export const ROLE_LABEL: Record<string, string> = { healthy: 'Healthy routine', recovery: 'Catch-up / recovery', rebel: 'Rebel day' }
export const timelineLabel = (t: Timeline) => `${t.role ? ROLE_ICON[t.role] + ' ' : ''}${t.name}`

/** "Keeps every calendar event" / "No calendar events - your calendar is cleared" */
export function calendarNote(t: Timeline): string {
  if (!t.skippedEvents.length) return 'Keeps every calendar event'
  if (!t.keptEventIds.length) return 'No calendar events - your calendar is cleared for this version'
  return `Skips: ${t.skippedEvents.join(', ')}`
}
