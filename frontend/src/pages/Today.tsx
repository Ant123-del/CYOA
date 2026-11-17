import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { addDays, fmtTime, isoDate, nowHM, prettyDate } from '../lib/dates'
import { KindBadge, StorylineLegend, optionColor } from '../components/Adventure'
import type { Chapter, DayPlan } from '../types'

const CAL_MSG: Record<string, string> = {
  created: 'Added to your Google Calendar ✓',
  existing: "It's already on your calendar ✓",
  not_connected: 'Chosen. Connect Google Calendar in Settings to auto-schedule.',
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

  // The chapter that needs a decision now: the current one, else the next unchosen one.
  const activeId = useMemo(() => {
    if (!plan) return null
    if (focusId && plan.chapters.some((c) => c.id === focusId)) return focusId
    if (!isToday) return plan.chapters.find((c) => !c.chosenOptionId)?.id ?? null
    const current = plan.chapters.find((c) => c.start <= now && now < c.end && !c.chosenOptionId)
    if (current) return current.id
    return plan.chapters.find((c) => c.start >= now && !c.chosenOptionId)?.id ?? null
  }, [plan, now, isToday, focusId])

  const choose = async (c: Chapter, optionId: string) => {
    setBusy(optionId)
    try {
      const res = await api.choose(date, c.id, optionId)
      setPlan(res.plan)
      setExpanded(null)
      setToast(CAL_MSG[res.calendar] ?? `Chosen. (Calendar: ${res.calendar})`)
      if (focusId) setParams({ date })
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
      setExpanded(c.id)
      setToast('Path cleared. Pick a new one.')
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

  const chosenCount = plan?.chapters.filter((c) => c.chosenOptionId).length ?? 0

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
              {chosenCount}/{plan.chapters.length} chapters chosen
            </span>
            <div className="bar">
              <div style={{ width: `${plan.chapters.length ? (chosenCount / plan.chapters.length) * 100 : 0}%` }} />
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
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
          <StorylineLegend storylines={plan.storylines} />

          <ol className="timeline">
            {plan.chapters.map((c) => {
              const chosen = c.options.find((o) => o.id === c.chosenOptionId)
              const isActive = c.id === activeId
              const isPast = isToday && c.end <= now
              const isOpen = isActive || expanded === c.id
              return (
                <li
                  key={c.id}
                  className={`tl-item${isActive ? ' active' : ''}${isPast ? ' past' : ''}${chosen ? ' done' : ''}`}
                  style={chosen ? ({ '--c': optionColor(chosen, plan.storylines) } as CSSProperties) : undefined}
                >
                  <div className="tl-marker" />
                  <div className="tl-time">
                    {fmtTime(c.start)}
                    <span>{fmtTime(c.end)}</span>
                  </div>
                  <div className="tl-body">
                    <div className="tl-head" onClick={() => !isActive && setExpanded(expanded === c.id ? null : c.id)}>
                      <h3>
                        {c.title}
                        {c.source === 'calendar' && <span className="tag">📅</span>}
                      </h3>
                      {isActive && !chosen && <span className="now-pill">{isToday && c.start <= now ? 'Now' : 'Up next'}</span>}
                    </div>

                    {chosen && !isOpen && (
                      <div className="chosen-line">
                        <KindBadge option={chosen} storylines={plan.storylines} />
                        <span className="chosen-title">{chosen.title}</span>
                        <button className="btn ghost small" onClick={() => reset(c)} disabled={busy === c.id}>
                          Change course
                        </button>
                      </div>
                    )}

                    {!chosen && !isOpen && (
                      <div className="preview-line">
                        {c.options.map((o) => (
                          <KindBadge key={o.id} option={o} storylines={plan.storylines} />
                        ))}
                      </div>
                    )}

                    {isOpen && (
                      <>
                        {!chosen && <p className="prompt">Which way does the story go?</p>}
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
          <div className="foot-actions">
            <Link className="btn ghost small" to={`/plan?date=${date}`}>
              Edit this day's plan
            </Link>
          </div>
        </>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
