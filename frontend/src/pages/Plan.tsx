import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { addDays, fmtTime, isoDate, newId, prettyDate } from '../lib/dates'
import { KindBadge } from '../components/Adventure'
import type { Chapter, DayPlan, DaySummary, Option, OptionKind, Priority } from '../types'

const STORYLINE_COLORS = ['#7c5cff', '#16a394', '#e8833a', '#d6457a', '#3b82f6']

const emptyPlan = (date: string): DayPlan => ({
  date,
  priorities: '',
  dayStart: '08:00',
  dayEnd: '22:00',
  summary: '',
  storylines: [],
  chapters: [],
})

const newOption = (kind: OptionKind = 'route', storylineId: string | null = null): Option => ({
  id: newId(),
  kind,
  storylineId,
  title: '',
  detail: '',
  durationMinutes: null,
  goalIds: [],
})

export default function Plan() {
  const { settings } = useAuth()
  const [params, setParams] = useSearchParams()
  const date = params.get('date') ?? addDays(isoDate(), 1)
  const setDate = (d: string) => setParams({ date: d })

  const [plan, setPlan] = useState<DayPlan>(emptyPlan(date))
  const [exists, setExists] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [week, setWeek] = useState<DaySummary[]>([])
  const [useCalendar, setUseCalendar] = useState(true)
  const [routes, setRoutes] = useState(3)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const weekStart = isoDate()
  const weekDays = Array.from({ length: 8 }, (_, i) => addDays(weekStart, i))

  const loadWeek = useCallback(() => {
    api.days(weekStart, addDays(weekStart, 7)).then(setWeek).catch(() => {})
    
  }, [weekStart])

  useEffect(() => {
    loadWeek()
  }, [loadWeek])

  useEffect(() => {
    setError(null)
    setNotice(null)
    api
      .day(date)
      .then((p) => {
        setExists(Boolean(p))
        setPlan(p ?? emptyPlan(date))
        setDirty(false)
      })
      .catch((e) => setError(e.message))
  }, [date])

  const update = (fn: (p: DayPlan) => DayPlan) => {
    setPlan((p) => fn(structuredClone(p)))
    setDirty(true)
  }
  const updateChapter = (id: string, fn: (c: Chapter) => void) =>
    update((p) => {
      const c = p.chapters.find((x) => x.id === id)
      if (c) fn(c)
      return p
    })

  const pullFromBoard = async () => {
    try {
      const goals = await api.goals()
      const rank: Record<Priority, number> = { high: 0, medium: 1, low: 2 }
      const open = goals
        .filter((g) => g.status === 'todo' || g.status === 'doing')
        .sort((a, b) => rank[a.priority] - rank[b.priority])
      if (!open.length) {
        setNotice('No cards in To do / Doing yet - add some on the Board.')
        return
      }
      const text = open
        .map((g) => `- [${g.priority}] ${g.title}${g.estimateMinutes ? ` (~${g.estimateMinutes}m)` : ''}${g.dueDate ? ` due ${g.dueDate}` : ''}`)
        .join('\n')
      update((p) => ({ ...p, priorities: p.priorities ? `${p.priorities.trim()}\n${text}` : text }))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const generate = async () => {
    if (exists && plan.chapters.length && !confirm('Replace the current plan for this day with a new AI plan?')) return
    setBusy('generate')
    setError(null)
    try {
      const p = await api.planDay({
        date,
        priorities: plan.priorities,
        dayStart: plan.dayStart,
        dayEnd: plan.dayEnd,
        useCalendar: useCalendar && Boolean(settings?.googleConnected),
        routes,
      })
      setPlan(p)
      setExists(true)
      setDirty(false)
      loadWeek()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    setBusy('save')
    try {
      const saved = await api.saveDay(plan)
      setPlan(saved)
      setExists(true)
      setDirty(false)
      setNotice('Saved. Reminders are scheduled for each chapter.')
      loadWeek()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const importCalendar = async () => {
    setBusy('import')
    try {
      const chapters = await api.importCalendar(date)
      const known = new Set(plan.chapters.map((c) => c.calendarEventId).filter(Boolean))
      const fresh = chapters.filter((c) => !known.has(c.calendarEventId))
      update((p) => ({ ...p, chapters: [...p.chapters, ...fresh].sort((a, b) => a.start.localeCompare(b.start)) }))
      setNotice(fresh.length ? `Imported ${fresh.length} calendar event(s). Remember to save.` : 'No new timed events found.')
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? 'Connect Google Calendar in Settings first.' : (e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const regenerate = async (chapterId: string, hint: string) => {
    if (dirty) await api.saveDay(plan)
    setBusy(`regen-${chapterId}`)
    try {
      setPlan(await api.chapterOptions(date, chapterId, hint))
      setDirty(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const addChapter = () =>
    update((p) => {
      const last = p.chapters[p.chapters.length - 1]
      const start = last?.end ?? p.dayStart
      const [h, m] = start.split(':').map(Number)
      const end = `${String(Math.min(h + 1, 23)).padStart(2, '0')}:${String(m).padStart(2, '0')}`
      p.chapters.push({
        id: newId(),
        start,
        end,
        title: 'New chapter',
        priority: 'medium',
        source: 'custom',
        calendarEventId: null,
        options: p.storylines.length
          ? p.storylines.map((s) => newOption('route', s.id))
          : [newOption(), newOption()],
        chosenOptionId: null,
        chosenAt: null,
        scheduledEventId: null,
      })
      return p
    })

  const addStoryline = () =>
    update((p) => {
      p.storylines.push({
        id: newId(),
        name: `Route ${String.fromCharCode(65 + p.storylines.length)}`,
        description: '',
        color: STORYLINE_COLORS[p.storylines.length % STORYLINE_COLORS.length],
      })
      return p
    })

  const summaryFor = (d: string) => week.find((w) => w.date === d)

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Plan an adventure</h1>
          <p className="muted">Set up tomorrow (or next week). Every chapter gets backup routes of the same priority.</p>
        </div>
        <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
      </div>

      <div className="week-strip">
        {weekDays.map((d) => {
          const s = summaryFor(d)
          return (
            <button key={d} className={`week-day${d === date ? ' active' : ''}`} onClick={() => setDate(d)}>
              <span className="wd">{prettyDate(d, { weekday: 'short' })}</span>
              <span className="dn">{prettyDate(d, { day: 'numeric' })}</span>
              <span className={`wk-status${s ? ' planned' : ''}`}>{s ? `${s.chapters} ch` : '—'}</span>
            </button>
          )
        })}
      </div>

      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      {notice && (
        <div className="banner info" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      <div className="plan-grid">
        <aside className="panel setup">
          <h2>{prettyDate(date)}</h2>
          <label>
            Today's priorities
            <textarea
              rows={8}
              placeholder={'What matters most this day?\ne.g. Finish the pitch deck, gym, call mom, low-energy afternoon likely'}
              value={plan.priorities}
              onChange={(e) => update((p) => ({ ...p, priorities: e.target.value }))}
            />
          </label>
          <button className="btn ghost small" onClick={pullFromBoard}>
            📋 Pull priorities from Board
          </button>
          <div className="row">
            <label>
              Day starts
              <input type="time" value={plan.dayStart} onChange={(e) => update((p) => ({ ...p, dayStart: e.target.value }))} />
            </label>
            <label>
              Day ends
              <input type="time" value={plan.dayEnd} onChange={(e) => update((p) => ({ ...p, dayEnd: e.target.value }))} />
            </label>
          </div>
          <label>
            Storylines (routes)
            <div className="seg">
              {[2, 3, 4].map((n) => (
                <button key={n} className={routes === n ? 'on' : ''} onClick={() => setRoutes(n)}>
                  {n}
                </button>
              ))}
            </div>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={useCalendar && Boolean(settings?.googleConnected)}
              disabled={!settings?.googleConnected}
              onChange={(e) => setUseCalendar(e.target.checked)}
            />
            Pair with my Google Calendar
            {!settings?.googleConnected && (
              <Link to="/settings" className="small-link">
                connect
              </Link>
            )}
          </label>
          <button className="btn primary big" onClick={generate} disabled={busy !== null}>
            {busy === 'generate' ? '✨ Writing your story…' : '✨ Generate my adventure'}
          </button>
          <div className="divider" />
          <div className="stack">
            <button className="btn ghost small" onClick={importCalendar} disabled={busy !== null || !settings?.googleConnected}>
              📅 Import calendar events
            </button>
            <button className="btn ghost small" onClick={addChapter}>
              + Add chapter manually
            </button>
          </div>
        </aside>

        <section className="panel editor">
          <div className="editor-head">
            <div>
              <h2>Storylines</h2>
              {plan.summary && <p className="summary">{plan.summary}</p>}
            </div>
            <div className="editor-actions">
              {exists && (
                <Link className="btn ghost small" to={`/today?date=${date}`}>
                  Play this day →
                </Link>
              )}
              <button className="btn primary" onClick={save} disabled={!dirty || busy !== null}>
                {busy === 'save' ? 'Saving…' : dirty ? 'Save plan' : 'Saved'}
              </button>
            </div>
          </div>

          <div className="storyline-edit">
            {plan.storylines.map((s) => (
              <div key={s.id} className="storyline-chip" style={{ borderColor: s.color ?? undefined }}>
                <span className="dot" style={{ background: s.color ?? 'var(--accent)' }} />
                <input
                  value={s.name}
                  onChange={(e) =>
                    update((p) => {
                      p.storylines.find((x) => x.id === s.id)!.name = e.target.value
                      return p
                    })
                  }
                />
                <button
                  className="icon-btn"
                  title="Remove storyline"
                  onClick={() =>
                    update((p) => {
                      p.storylines = p.storylines.filter((x) => x.id !== s.id)
                      return p
                    })
                  }
                >
                  ×
                </button>
              </div>
            ))}
            <button className="btn ghost small" onClick={addStoryline}>
              + Storyline
            </button>
          </div>

          {plan.chapters.length === 0 ? (
            <div className="empty">
              <div className="compass">🗺️</div>
              <p>
                No chapters yet. Write your priorities and hit <b>Generate my adventure</b>, or import your calendar.
              </p>
            </div>
          ) : (
            <ol className="chapter-list">
              {plan.chapters.map((c, i) => (
                <ChapterEditor
                  key={c.id}
                  index={i}
                  chapter={c}
                  plan={plan}
                  busy={busy === `regen-${c.id}`}
                  onChange={(fn) => updateChapter(c.id, fn)}
                  onDelete={() =>
                    update((p) => {
                      p.chapters = p.chapters.filter((x) => x.id !== c.id)
                      return p
                    })
                  }
                  onRegenerate={(hint) => regenerate(c.id, hint)}
                />
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  )
}

function ChapterEditor({
  index,
  chapter: c,
  plan,
  busy,
  onChange,
  onDelete,
  onRegenerate,
}: {
  index: number
  chapter: Chapter
  plan: DayPlan
  busy: boolean
  onChange: (fn: (c: Chapter) => void) => void
  onDelete: () => void
  onRegenerate: (hint: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [hint, setHint] = useState('')

  return (
    <li className={`chapter-edit${c.chosenOptionId ? ' chosen' : ''}`}>
      <div className="chapter-edit-head" onClick={() => setOpen(!open)}>
        <span className="chapter-num">{index + 1}</span>
        <span className="chapter-time">
          {fmtTime(c.start)} – {fmtTime(c.end)}
        </span>
        <span className="chapter-title">{c.title}</span>
        {c.source === 'calendar' && <span className="tag">📅 calendar</span>}
        <span className={`tag prio prio-${c.priority}`}>{c.priority}</span>
        <span className="option-dots">
          {c.options.map((o) => (
            <KindBadge key={o.id} option={o} storylines={plan.storylines} />
          ))}
        </span>
        <span className="chev">{open ? '▾' : '▸'}</span>
      </div>

      {open && (
        <div className="chapter-edit-body">
          <div className="row">
            <label>
              Start
              <input type="time" value={c.start} onChange={(e) => onChange((x) => void (x.start = e.target.value))} />
            </label>
            <label>
              End
              <input type="time" value={c.end} onChange={(e) => onChange((x) => void (x.end = e.target.value))} />
            </label>
            <label className="grow">
              Title
              <input value={c.title} onChange={(e) => onChange((x) => void (x.title = e.target.value))} />
            </label>
            <label>
              Priority
              <select value={c.priority} onChange={(e) => onChange((x) => void (x.priority = e.target.value as Priority))}>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
          </div>

          <div className="options-edit">
            {c.options.map((o, oi) => (
              <div key={o.id} className="option-edit">
                <select
                  value={o.kind}
                  onChange={(e) => onChange((x) => void (x.options[oi].kind = e.target.value as OptionKind))}
                >
                  <option value="yes">Yes</option>
                  <option value="yes_and">Yes, and…</option>
                  <option value="no">No</option>
                  <option value="no_and">No, and…</option>
                  <option value="route">Route</option>
                </select>
                <select
                  value={o.storylineId ?? ''}
                  onChange={(e) => onChange((x) => void (x.options[oi].storylineId = e.target.value || null))}
                >
                  <option value="">No storyline</option>
                  {plan.storylines.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <input
                  className="grow"
                  placeholder="What you'd do"
                  value={o.title}
                  onChange={(e) => onChange((x) => void (x.options[oi].title = e.target.value))}
                />
                <input
                  className="mins"
                  type="number"
                  min={5}
                  placeholder="min"
                  value={o.durationMinutes ?? ''}
                  onChange={(e) =>
                    onChange((x) => void (x.options[oi].durationMinutes = e.target.value ? Number(e.target.value) : null))
                  }
                />
                <button className="icon-btn" title="Remove option" onClick={() => onChange((x) => void x.options.splice(oi, 1))}>
                  ×
                </button>
                <input
                  className="detail"
                  placeholder="Details (optional)"
                  value={o.detail}
                  onChange={(e) => onChange((x) => void (x.options[oi].detail = e.target.value))}
                />
              </div>
            ))}
            <button className="btn ghost small" onClick={() => onChange((x) => void x.options.push(newOption()))}>
              + Option
            </button>
          </div>

          <div className="regen">
            <input
              placeholder="Ask the AI for different options… (e.g. 'something outdoors', 'I'll be tired')"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
            />
            <button className="btn ghost small" onClick={() => onRegenerate(hint)} disabled={busy}>
              {busy ? 'Thinking…' : '✨ Reroll options'}
            </button>
            <span className="spacer" />
            <button className="btn danger ghost small" onClick={onDelete}>
              Delete chapter
            </button>
          </div>
        </div>
      )}
    </li>
  )
}
