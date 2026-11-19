import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { fmtTime, isoDate, nowHM } from '../lib/dates'
import { pathChapters, timelineById } from '../lib/path'
import { HopeCheckIn, KIND_META, ProblemNote } from './Manifestations'
import { KindBadge, SourceTag, SwitchTag, TimelineBadge, optionColor } from './Adventure'
import type { Chapter, DayPlan, Manifestation, Option } from '../types'

const CAL_MSG: Record<string, string> = {
  created: 'It’s on your Google Calendar from now.',
  existing: 'It’s already on your calendar.',
  not_connected: 'Link your Google Calendar in Settings to auto-schedule.',
  no_writable: 'Your linked calendars are all view-only, so nothing was added.',
  skipped: '',
}

type Choice = { chapter: Chapter; option: Option }

/** What you're in right now: the chosen chapter on your path that covers this minute. */
function currentTask(plan: DayPlan, now: string): Choice | null {
  const ch = pathChapters(plan).find((c) => c.chosenOptionId && c.start <= now && now < c.end)
  const option = ch?.options.find((o) => o.id === ch.chosenOptionId)
  return ch && option ? { chapter: ch, option } : null
}

/**
 * Every option, across all storylines and all timelines, for the time range you're in:
 * the current task's start-end, or just "now" when you're between tasks.
 */
function alternatives(plan: DayPlan, now: string, current: Choice | null): Chapter[] {
  const from = current ? current.chapter.start : now
  const to = current ? current.chapter.end : now
  return plan.chapters
    .filter((c) => c.start <= to && c.end > from && c.end > now)
    .map((c) => ({ ...c, options: c.options.filter((o) => !(c.id === current?.chapter.id && o.id === current.option.id)) }))
    .filter((c) => c.options.length)
    .sort((a, b) => a.start.localeCompare(b.start) || (a.timelineId ?? '').localeCompare(b.timelineId ?? ''))
}

type Phase =
  | { name: 'checkin' }
  | { name: 'reflect'; item: Manifestation | null }
  | { name: 'switch'; item: Manifestation | null }
  | { name: 'done'; title: string; note: string }

/** Struggle mode: check in during a task, hear your corrected manifestation, then stay or switch. */
export function StruggleMode({ onClose }: { onClose: () => void }) {
  const date = isoDate()
  const [plan, setPlan] = useState<DayPlan | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [phase, setPhase] = useState<Phase>({ name: 'checkin' })
  const [busy, setBusy] = useState<string | null>(null)
  const [now] = useState(nowHM)

  useEffect(() => {
    api
      .day(date)
      .then(setPlan)
      .catch((e) => {
        setError(e.message)
        setPlan(null)
      })
  }, [date])

  const current = useMemo(() => (plan ? currentTask(plan, now) : null), [plan, now])
  const options = useMemo(() => (plan ? alternatives(plan, now, current) : []), [plan, now, current])

  const choose = async ({ chapter, option }: Choice) => {
    setBusy(option.id)
    setError(null)
    try {
      const before = plan?.currentTimelineId
      const res = await api.choose(date, chapter.id, option.id)
      setPlan(res.plan)
      const moved = res.plan.currentTimelineId && res.plan.currentTimelineId !== before ? timelineById(res.plan, res.plan.currentTimelineId) : null
      const note = [CAL_MSG[res.calendar] ?? '', moved ? `Your day now follows “${moved.name}”.` : ''].filter(Boolean).join(' ')
      setPhase({ name: 'done', title: option.title, note })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (phase.name === 'checkin') {
    return (
      <HopeCheckIn
        context="Struggling with"
        taskTitle={plan === undefined ? '…' : current ? current.option.title : 'right now'}
        continueLabel="Next →"
        onCancel={onClose}
        onContinue={(item) => setPhase({ name: 'reflect', item })}
      />
    )
  }

  const reminder = (item: Manifestation | null) =>
    item && (
      <>
        <ProblemNote item={item} />
        {(item.kind === 'positive' || item.corrected) && (
          <div className={`mantra${item.kind === 'positive' ? ' positive' : ''}`}>
            <span className="muted small">
              {KIND_META[item.kind].icon} {item.kind === 'complicated' ? 'Repeat to yourself' : item.title}
            </span>
            <p>{item.kind === 'complicated' ? item.corrected : item.description || item.title}</p>
          </div>
        )}
      </>
    )

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal hope-modal struggle" onClick={(e) => e.stopPropagation()}>
        {error && <div className="banner error">{error}</div>}

        {phase.name === 'reflect' && (
          <>
            <h2>Take a breath.</h2>
            {reminder(phase.item)}
            <p className="muted">
              {current ? (
                <>
                  You're on <strong>{current.option.title}</strong> until {fmtTime(current.chapter.end)}. Stay with it, or switch to
                  something else for this time.
                </>
              ) : (
                'You can stay with what you’re doing, or switch to something else for this time.'
              )}
            </p>
            <div className="modal-actions">
              <button className="btn ghost" onClick={onClose}>
                Stay with it
              </button>
              <span className="spacer" />
              <button className="btn primary" onClick={() => setPhase({ name: 'switch', item: phase.item })}>
                Switch to another task
              </button>
            </div>
          </>
        )}

        {phase.name === 'switch' && (
          <>
            <h2>What else fits {current ? `${fmtTime(current.chapter.start)}–${fmtTime(current.chapter.end)}` : 'right now'}?</h2>
            {reminder(phase.item)}
            {plan === undefined && <p className="muted">Loading your day…</p>}
            {plan === null && (
              <div className="empty">
                <p>There's no plan for today yet.</p>
                <Link className="btn ghost small" to="/plan" onClick={onClose}>
                  Plan today
                </Link>
              </div>
            )}
            {plan && options.length === 0 && <p className="muted">Nothing else is planned for this time, in any storyline or timeline.</p>}
            {plan && options.length > 0 && (
              <>
                <p className="muted small">Every storyline and timeline for this time.</p>
                <div className="struggle-options">
                  {options.map((c) => {
                    const tl = timelineById(plan, c.timelineId)
                    return (
                      <section key={c.id} className="struggle-chapter">
                        <div className="struggle-chapter-head">
                          <span className="muted small">
                            {fmtTime(c.start)}–{fmtTime(c.end)}
                          </span>
                          <strong>{c.title}</strong>
                          <SourceTag chapter={c} />
                          <TimelineBadge timeline={tl} />
                        </div>
                        <div className="paths">
                          {c.options.map((o) => (
                            <button
                              key={o.id}
                              className="path"
                              style={{ '--c': optionColor(o, plan.storylines) } as CSSProperties}
                              onClick={() => choose({ chapter: c, option: o })}
                              disabled={busy !== null}
                            >
                              <KindBadge option={o} storylines={plan.storylines} />
                              <span className="path-title">{o.title}</span>
                              {o.detail && <span className="path-detail">{o.detail}</span>}
                              <SwitchTag option={o} timelines={plan.timelines} />
                              <span className="path-foot">
                                {o.durationMinutes ? `${o.durationMinutes} min` : ''}
                                <span className="go">{busy === o.id ? 'Switching…' : 'Switch →'}</span>
                              </span>
                            </button>
                          ))}
                        </div>
                      </section>
                    )
                  })}
                </div>
              </>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setPhase({ name: 'reflect', item: phase.item })}>
                ‹ Back
              </button>
              <span className="spacer" />
              <button className="btn ghost" onClick={onClose}>
                Stay with it
              </button>
            </div>
          </>
        )}

        {phase.name === 'done' && (
          <>
            <h2>Switched to {phase.title}.</h2>
            {phase.note && <p className="muted">{phase.note}</p>}
            <div className="modal-actions">
              <Link className="btn ghost" to="/today" onClick={onClose}>
                See today
              </Link>
              <span className="spacer" />
              <button className="btn primary" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
