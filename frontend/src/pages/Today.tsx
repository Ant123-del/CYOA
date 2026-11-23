import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { addDays, fmtTime, isoDate, nowHM, prettyDate } from '../lib/dates'
import { SourceTag, KindBadge, StorylineLegend, SwitchTag, TimelineBadge, calendarNote, optionColor } from '../components/Adventure'
import TimelineMap from '../components/TimelineMap'
import RevisePanel from '../components/RevisePanel'
import { currentTimeline, hasTimelines, pathChapters, timelineById } from '../lib/path'
import StorylineLanes from '../components/StorylineLanes'
import ViewToggle, { useDayView } from '../components/ViewToggle'
import { SleepCard } from '../components/Sleep'
import { PatienceCheckIn } from '../components/Patience'
import { usePatience } from '../lib/patience'
import type { Chapter, DayPlan } from '../types'

const CAL_MSG: Record<string, string> = {
  created: 'Added to your Google Calendar ✓',
  existing: "It's already on your calendar ✓",
  not_connected: 'Chosen. Link your Google Calendar in Settings to auto-schedule.',
  no_writable: 'Chosen. Your linked calendars are all view-only - let CYOA edit one in Settings to auto-schedule.',
  skipped: 'Chosen.',
}

export default function Today() {
  const { settings } = useAuth()
  const [params, setParams] = useSearchParams()
  const date = params.get('date') ?? isoDate()
  const focusId = params.get('chapter')
  const [plan, setPlan] = useState<DayPlan | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [now, setNow] = useState(nowHM())
  const [expanded, setExpanded] = useState<string | null>(null)
  const [view, setView] = useDayView()
  const [showRevise, setShowRevise] = useState(false)
  // A path waiting on its patience check-in: before you start it, or after it's done.
  const [pending, setPending] = useState<{ chapter: Chapter; optionId: string; phase: 'before' | 'after' } | null>(null)
  const { patience, set: setPatience, refresh: refreshPatience } = usePatience()
  const toggleRevise = () => {
    const open = !showRevise
    setShowRevise(open)
    if (open) setTimeout(() => document.getElementById('revise-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  useEffect(() => {
    const t = setInterval(() => setNow(nowHM()), 30_000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    setPlan(undefined)
    setExpanded(null)
    api
      .day(date)
      .then(setPlan)
      .catch((e) => {
        setError(e.message)
        setPlan(null)
      })
  }, [date])

  const isToday = date === isoDate()
  const branching = plan ? hasTimelines(plan) : false
  // With timelines, show the person's path (what they chose + what's ahead), not every version.
  const chapters = useMemo(() => (plan ? pathChapters(plan) : []), [plan])
  const here = plan ? currentTimeline(plan) : null

  // The chapter that needs a decision now: the current one, else the next unchosen one.
  const activeId = useMemo(() => {
    if (!plan) return null
    if (focusId && plan.chapters.some((c) => c.id === focusId)) return focusId
    if (!isToday) return chapters.find((c) => !c.chosenOptionId)?.id ?? null
    const current = chapters.find((c) => c.start <= now && now < c.end && !c.chosenOptionId)
    if (current) return current.id
    return chapters.find((c) => c.start >= now && !c.chosenOptionId)?.id ?? null
  }, [plan, chapters, now, isToday, focusId])

  const commitChoice = async (c: Chapter, optionId: string): Promise<boolean> => {
    setBusy(optionId)
    try {
      const before = plan?.currentTimelineId
      const res = await api.choose(date, c.id, optionId)
      setPlan(res.plan)
      setExpanded(null)
      const moved = res.plan.currentTimelineId && res.plan.currentTimelineId !== before ? timelineById(res.plan, res.plan.currentTimelineId) : null
      const msg = CAL_MSG[res.calendar] ?? `Chosen. (Calendar: ${res.calendar})`
      setToast(moved ? `${msg} Your day now follows “${moved.name}”.` : msg)
      if (focusId) setParams({ date })
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  const isPastDay = date < isoDate()
  // A chapter is missed if they said so, or (by default) if its time passed without a choice.
  const isMissed = (c: Chapter) =>
    !c.chosenOptionId && (Boolean(c.missed) || (settings?.assumeMissed !== false && (isPastDay || (isToday && c.end <= now))))
  const toggleChapter = (c: Chapter) => setExpanded(expanded === c.id ? null : c.id)

  // Every path gets a patience check-in. Starting one asks what it will cost or give
  // you; picking one after its time (or after missing it) asks what it did.
  const isOver = (c: Chapter) => isPastDay || (isToday && c.end <= now)
  const choose = (c: Chapter, optionId: string) =>
    setPending({ chapter: c, optionId, phase: isMissed(c) || isOver(c) ? 'after' : 'before' })

  const taskEntry = (c: Chapter) => patience?.entries.find((e) => e.id === `task_${date}_${c.id}`)
  // Started (or finished) tasks you haven't said how they went yet.
  const canSettle = (c: Chapter) => {
    if (!c.chosenOptionId || !patience || (!isPastDay && !(isToday && c.start <= now))) return false
    const e = taskEntry(c)
    return e ? !e.settled : Boolean(c.chosenAt && c.chosenAt >= patience.startedAt)
  }
  const toSettle = chapters.filter((c) => canSettle(c) && isOver(c))
  const settle = (c: Chapter) => c.chosenOptionId && setPending({ chapter: c, optionId: c.chosenOptionId, phase: 'after' })

  const checkIn = async (amount: number, minutes: number | null) => {
    if (!pending) return
    const { chapter, optionId, phase } = pending
    const alreadyChosen = chapter.chosenOptionId === optionId
    if (!alreadyChosen && !(await commitChoice(chapter, optionId))) return setPending(null)
    setPatience(await api.patienceTask({ date, chapterId: chapter.id, optionId, phase, amount, minutes }))
    setPending(null)
    if (alreadyChosen) setToast(`Checked in: ${amount >= 0 ? 'gave you' : 'cost you'} ${Math.abs(amount)} patience.`)
  }

  const setMissed = async (c: Chapter, missed: boolean) => {
    setBusy(c.id)
    try {
      setPlan(await api.setMissed(date, c.id, missed))
      setExpanded(null)
      setToast(missed ? 'Marked as missed - no worries.' : 'Back on your path.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const reset = async (c: Chapter) => {
    setBusy(c.id)
    try {
      setPlan(await api.resetChoice(date, c.id))
      refreshPatience() // its patience is refunded
      setExpanded(c.id)
      setToast('Path cleared, and its patience refunded. Pick a new one.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(t)
  }, [toast])

  const chosenCount = chapters.filter((c) => c.chosenOptionId).length

  return (
    <div className="page today">
      <div className="page-head">
        <div>
          <div className="date-nav">
            <button className="icon-btn" onClick={() => setParams({ date: addDays(date, -1) })} aria-label="Previous day">
              ‹
            </button>
            <h1>{isToday ? 'Today' : prettyDate(date)}</h1>
            <button className="icon-btn" onClick={() => setParams({ date: addDays(date, 1) })} aria-label="Next day">
              ›
            </button>
            {!isToday && (
              <button className="btn ghost small" onClick={() => setParams({})}>
                Jump to today
              </button>
            )}
          </div>
          <p className="muted">
            {isToday ? prettyDate(date) : 'Preview'}
            {settings?.timezone ? ` · ${settings.timezone}` : ''}
          </p>
        </div>
        {plan && (
          <div className="progress">
            <span>
              {chosenCount}/{chapters.length} chapters chosen
            </span>
            <div className="bar">
              <div style={{ width: `${chapters.length ? (chosenCount / chapters.length) * 100 : 0}%` }} />
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      {isToday && <SleepCard />}

      {toSettle.length > 0 && (
        <div className="banner info settle-banner">
          <span>
            {toSettle.length === 1 ? `“${toSettle[0].title}” is done.` : `${toSettle.length} tasks are done.`} How much patience did{' '}
            {toSettle.length === 1 ? 'it' : 'they'} cost or give you?
          </span>
          <button className="btn small primary" onClick={() => settle(toSettle[0])}>
            Check in
          </button>
        </div>
      )}

      {plan === undefined && <p className="muted">Loading your story…</p>}

      {plan === null && (
        <div className="empty big">
          <div className="compass">🗺️</div>
          <h2>No adventure written for this day</h2>
          <p className="muted">Plan it ahead with a few routes, so you've always got a backup.</p>
          <Link className="btn primary" to={`/plan?date=${date}`}>
            Plan this day
          </Link>
        </div>
      )}

      {plan && (
        <>
          {plan.summary && <p className="summary lead">{plan.summary}</p>}
          {branching && here && (
            <div className="here-banner" style={{ '--c': here.color ?? 'var(--accent)' } as CSSProperties}>
              <div>
                <span className="muted small">You're on</span> <TimelineBadge timeline={here} />
              </div>
              <p>{here.description}</p>
              <p className="muted small">
                {calendarNote(here)}.{' '}
                {(plan.timelines?.length ?? 0) > 1 && 'Options marked → take you onto another version of the day.'}
              </p>
            </div>
          )}
          {showRevise && (
            <div id="revise-panel">
              <RevisePanel
                plan={plan}
                onPlan={(p) => {
                  setPlan(p)
                  setToast('Plan revised ✓')
                }}
              />
            </div>
          )}
          <div className="view-row">
            <ViewToggle
              view={view}
              onChange={setView}
              firstLabel={branching ? 'Your path' : 'Timeline'}
              secondLabel={branching ? 'All timelines' : 'Storylines'}
            />
            <span className="muted small">
              {view === 'storylines'
                ? branching
                  ? 'Every version of your day side by side. Storylines (the colours) weave between them.'
                  : 'Each column is one route through your day - follow one, or switch whenever you like.'
                : 'Your day, chapter by chapter.'}
            </span>
            <button className="btn ghost small view-row-end" onClick={() => toggleRevise()}>
              {showRevise ? 'Hide revise panel' : '✏️ Revise with AI'}
            </button>
          </div>
          {view === 'storylines' ? (
            branching ? (
              <TimelineMap plan={plan} busy={busy} onChoose={choose} />
            ) : (
              <StorylineLanes plan={plan} activeId={activeId} busy={busy} onChoose={choose} />
            )
          ) : (
            <>
          <StorylineLegend storylines={plan.storylines} />

          <ol className="timeline">
            {chapters.map((c) => {
              const chosen = c.options.find((o) => o.id === c.chosenOptionId)
              const otherTimeline = branching && c.timelineId !== here?.id ? timelineById(plan, c.timelineId) : null
              const isActive = c.id === activeId
              const isPast = isToday && c.end <= now
              const missed = isMissed(c)
              const isOpen = isActive || expanded === c.id
              return (
                <li
                  key={c.id}
                  className={`tl-item${isActive ? ' active' : ''}${isPast ? ' past' : ''}${chosen ? ' done' : ''}${missed && !isOpen ? ' missed' : ''}`}
                  style={chosen ? ({ '--c': optionColor(chosen, plan.storylines) } as CSSProperties) : undefined}
                >
                  <div className="tl-marker" />
                  <div className="tl-time">
                    {fmtTime(c.start)}
                    <span>{fmtTime(c.end)}</span>
                  </div>
                  <div className="tl-body">
                    <div className="tl-head" onClick={() => !isActive && toggleChapter(c)}>
                      <h3>
                        {c.title}
                        <SourceTag chapter={c} />
                        {otherTimeline && <TimelineBadge timeline={otherTimeline} />}
                      </h3>
                      {isActive && !chosen && <span className="now-pill">{isToday && c.start <= now ? 'Now' : 'Up next'}</span>}
                    </div>

                    {chosen && !isOpen && (
                      <div className="chosen-line">
                        <KindBadge option={chosen} storylines={plan.storylines} />
                        <span className="chosen-title">{chosen.title}</span>
                        <SwitchTag option={chosen} timelines={plan.timelines} />
                        {canSettle(c) && (
                          <button className="btn small settle-btn" onClick={() => settle(c)}>
                            ⏳ How did it go?
                          </button>
                        )}
                        {(() => {
                          const e = taskEntry(c)
                          return e ? <span className={`ledger-amount ${e.kind}`}>{e.settled ? '' : '~'}{e.amount >= 0 ? '+' : ''}{e.amount}</span> : null
                        })()}
                        <button className="btn ghost small" onClick={() => reset(c)} disabled={busy === c.id}>
                          Change course
                        </button>
                      </div>
                    )}

                    {missed && !isOpen && (
                      <div className="chosen-line">
                        <span className="tag missed-tag">Missed</span>
                        <span className="chosen-title muted">That's okay - the day moved on.</span>
                        <button className="btn ghost small" onClick={() => setExpanded(c.id)} disabled={busy !== null}>
                          Actually, I did this
                        </button>
                        {c.missed && (
                          <button className="btn ghost small" onClick={() => setMissed(c, false)} disabled={busy !== null}>
                            Undo
                          </button>
                        )}
                      </div>
                    )}

                    {!chosen && !missed && !isOpen && (
                      <div className="preview-line">
                        {c.options.map((o) => (
                          <span key={o.id} className="preview-opt">
                            <KindBadge option={o} storylines={plan.storylines} />
                            <SwitchTag option={o} timelines={plan.timelines} />
                          </span>
                        ))}
                      </div>
                    )}

                    {isOpen && (
                      <>
                        {!chosen && (
                          <div className="prompt-row">
                            <p className="prompt">{missed ? 'Which way did it go?' : 'Which way does the story go?'}</p>
                            {!c.missed && (
                              <button className="btn ghost small" onClick={() => setMissed(c, true)} disabled={busy !== null}>
                                I missed this
                              </button>
                            )}
                          </div>
                        )}
                        <div className="paths">
                          {c.options.map((o) => (
                            <button
                              key={o.id}
                              className={`path${o.id === c.chosenOptionId ? ' picked' : ''}`}
                              style={{ '--c': optionColor(o, plan.storylines) } as CSSProperties}
                              onClick={() => choose(c, o.id)}
                              disabled={busy !== null}
                            >
                              <KindBadge option={o} storylines={plan.storylines} />
                              <span className="path-title">{o.title}</span>
                              {o.detail && <span className="path-detail">{o.detail}</span>}
                              <SwitchTag option={o} timelines={plan.timelines} />
                              <span className="path-foot">
                                {o.durationMinutes ? `${o.durationMinutes} min` : ''}
                                <span className="go">{busy === o.id ? 'Scheduling…' : o.id === c.chosenOptionId ? 'Chosen' : 'Choose →'}</span>
                              </span>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
            </>
          )}
          <div className="foot-actions">
            <button className="btn ghost small" onClick={() => toggleRevise()}>
              {showRevise ? 'Hide revise panel' : '✏️ Revise with AI'}
            </button>
            <Link className="btn ghost small" to={`/plan?date=${date}`}>
              Edit this day's plan
            </Link>
          </div>
        </>
      )}

      {pending && (() => {
        const option = pending.chapter.options.find((o) => o.id === pending.optionId)
        return option ? (
          <PatienceCheckIn
            key={`${pending.chapter.id}-${pending.optionId}-${pending.phase}`}
            phase={pending.phase}
            date={date}
            chapter={pending.chapter}
            option={option}
            expected={taskEntry(pending.chapter)?.expected}
            onCancel={() => setPending(null)}
            onConfirm={checkIn}
          />
        ) : null
      })()}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
