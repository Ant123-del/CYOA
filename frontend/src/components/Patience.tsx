import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { curveText, fmtPoints, parabola, usePatience } from '../lib/patience'
import type { Chapter, Option, PatienceEntry, PatienceSuggestion, PatienceSummary, TagPatience } from '../types'

const SOURCE_ICON: Record<PatienceEntry['source'], string> = {
  start: '🌱',
  open: '👀',
  revise: '✏️',
  sleep: '🛌',
  task: '✅',
  log: '✍️',
  interest: '📉',
}

const BASIS: Record<PatienceSuggestion['basis'], (s: PatienceSuggestion) => string> = {
  history: (s) => `The average of your ${s.samples} past score${s.samples === 1 ? '' : 's'} for this.`,
  tag: (s) => `Your Board default for ${s.tags.map((t) => `#${t}`).join(', ')}.`,
  need: () => 'A want or need: it gives most at its climax, and less (then costs you) past it.',
  average: (s) => `Nothing for this yet, so the average of all ${s.samples} of your task scores.`,
  fallback: () => 'A first guess. Your scores will make it more accurate.',
}

/** The balance in the top bar. */
export function PatiencePill() {
  const { patience } = usePatience()
  if (!patience) return null
  const debt = patience.balance < 0
  return (
    <Link
      to="/hope"
      className={`pill patience-pill${debt ? ' debt' : ''}`}
      title={debt ? `In debt: ${patience.interestPerHour}% interest an hour until you pay it back` : 'Patience: the currency of hope'}
    >
      <span aria-hidden>⏳</span> {Math.round(patience.balance * 10) / 10}
    </Link>
  )
}

export function Balance({ amount, interest }: { amount: number; interest?: number }) {
  return (
    <span className={`balance${amount < 0 ? ' debt' : ''}`}>
      ⏳ {Math.round(amount * 10) / 10}
      {amount < 0 && interest != null && <span className="small"> · {interest}% interest an hour</span>}
    </span>
  )
}

function Points({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const step = (d: number) => onChange(Math.round((value + d) * 10) / 10)
  return (
    <div className="points">
      <button type="button" className="icon-btn" onClick={() => step(-1)} aria-label="Less">
        −
      </button>
      <input type="number" step={0.5} value={value} onChange={(e) => onChange(Number(e.target.value) || 0)} />
      <button type="button" className="icon-btn" onClick={() => step(1)} aria-label="More">
        +
      </button>
      <span className={`points-word ${value >= 0 ? 'emission' : 'absorption'}`}>
        {value >= 0 ? `Gives you ${value}` : `Costs you ${-value}`}
        <span className="muted small">{value >= 0 ? ' · emission' : ' · absorption'}</span>
      </span>
    </div>
  )
}

/**
 * The check-in before a task ("how much patience will this cost / give you?") or after
 * it ("how much did it?"). The default is the average of your past scores.
 */
export function PatienceCheckIn({
  phase,
  date,
  chapter,
  option,
  expected,
  onConfirm,
  onCancel,
}: {
  phase: 'before' | 'after'
  date: string
  chapter: Chapter
  option: Option
  expected?: number | null
  onConfirm: (amount: number, minutes: number | null) => Promise<void> | void
  onCancel: () => void
}) {
  const { patience } = usePatience()
  const [s, setS] = useState<PatienceSuggestion | null>(null)
  const [amount, setAmount] = useState(0)
  const [minutes, setMinutes] = useState<number | null>(null)
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .patienceSuggest(date, chapter.id, option.id)
      .then((r) => {
        setS(r)
        setAmount(r.amount)
        setMinutes(r.minutes)
      })
      .catch((e) => setError(e.message))
  }, [date, chapter.id, option.id])

  // For wants & needs the default follows the parabola as you change the time.
  const changeMinutes = (m: number | null) => {
    setMinutes(m)
    if (s?.profile && !touched) setAmount(parabola(s.profile, m))
  }

  const balance = patience?.balance ?? 0
  const after = Math.round((balance + amount) * 10) / 10
  const debt = phase === 'before' && amount < 0 && after < 0

  const confirm = async () => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(amount, minutes)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal patience-checkin" onClick={(e) => e.stopPropagation()}>
        <div className="checkin-head">
          <span className="muted small">
            {phase === 'before' ? 'Before you start' : 'How did it go'}: {option.title}
          </span>
          {patience && <Balance amount={patience.balance} interest={patience.interestPerHour} />}
        </div>
        <h2>{phase === 'before' ? 'How much patience will this cost or give you?' : 'How much patience did it cost or give you?'}</h2>
        {error && <div className="banner error">{error}</div>}
        {!s && !error && <p className="muted">Working out your default…</p>}
        {s && (
          <>
            {s.profile && (
              <label className="minutes-field">
                {phase === 'before' ? 'For how long?' : 'How long did it take?'}
                <span className="minutes-input">
                  <input
                    type="number"
                    min={0}
                    value={minutes ?? ''}
                    onChange={(e) => changeMinutes(e.target.value === '' ? null : Number(e.target.value))}
                  />
                  min
                </span>
                <span className="muted small">{curveText(s.profile)}</span>
              </label>
            )}
            <Points
              value={amount}
              onChange={(n) => {
                setTouched(true)
                setAmount(n)
              }}
            />
            <p className="muted small">
              {BASIS[s.basis](s)}
              {phase === 'after' && expected != null && <> You expected {fmtPoints(expected)}.</>}
            </p>
            {debt && (
              <div className="banner warn-banner debt-warning">
                <strong>This puts you at {after}.</strong> Debt grows by {patience?.interestPerHour}% every hour until you pay it back. Get some
                patience first if you can: eat, take a break, or sleep. If you take it on anyway, you'll have to pay it off.
              </div>
            )}
          </>
        )}
        <div className="modal-actions">
          <button className="btn ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <span className="spacer" />
          <button className={`btn ${debt ? 'danger' : 'primary'}`} onClick={confirm} disabled={!s || busy}>
            {busy ? 'Saving…' : debt ? 'Take it on anyway' : phase === 'before' ? 'Start →' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

const QUICK: { label: string; amount: number }[] = [
  { label: 'Ate something', amount: 2 },
  { label: 'Took a break', amount: 1 },
]

/** The Hope tab's patience account: balance, today's flow, logging, and the ledger. */
export function PatienceAccount() {
  const { patience, set } = usePatience()
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState(-1)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const byDay = useMemo(() => {
    const out: { date: string; items: PatienceEntry[] }[] = []
    for (const e of patience?.entries ?? []) {
      const last = out[out.length - 1]
      if (last?.date === e.date) last.items.push(e)
      else out.push({ date: e.date, items: [e] })
    }
    return out
  }, [patience])

  if (!patience) return <section className="panel patience-account muted">Loading your patience…</section>

  const run = async (fn: () => Promise<PatienceSummary>) => {
    setBusy(true)
    setError(null)
    try {
      set(await fn())
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const log = async (l: string, a: number) => {
    if (await run(() => api.patienceLog({ label: l, amount: a }))) setLabel('')
  }

  const debt = patience.balance < 0
  return (
    <section className={`panel patience-account${debt ? ' debt' : ''}`} id="patience">
      <div className="patience-head">
        <div>
          <h2>Patience</h2>
          <p className="muted small">
            The currency of hope. Fulfil your wants and needs to gain it (emission); routines, school, work, your to-do list, and checking
            the app spend it (absorption).
          </p>
        </div>
        <div className="patience-total">
          <span className={`patience-big${debt ? ' debt' : ''}`}>{Math.round(patience.balance * 10) / 10}</span>
          <span className="muted small">
            today <span className="emission">{fmtPoints(patience.emittedToday)}</span> / <span className="absorption">{fmtPoints(patience.absorbedToday)}</span>
          </span>
        </div>
      </div>
      {debt && (
        <div className="banner warn-banner">
          You're in debt. It grows by {patience.interestPerHour}% every hour. Before taking on anything new, look for patience: eat, take a
          break, or get some sleep.
        </div>
      )}
      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      <form
        className="patience-log"
        onSubmit={(e) => {
          e.preventDefault()
          if (label.trim()) log(label.trim(), amount)
        }}
      >
        <span className="muted small">Something that wasn't on your plan?</span>
        <div className="patience-log-row">
          {QUICK.map((q) => (
            <button key={q.label} type="button" className="btn ghost small" disabled={busy} onClick={() => log(q.label, q.amount)}>
              {q.label} {fmtPoints(q.amount)}
            </button>
          ))}
        </div>
        <div className="patience-log-row">
          <input placeholder="What happened?" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} />
          <input type="number" step={0.5} className="points-small" value={amount} onChange={(e) => setAmount(Number(e.target.value) || 0)} />
          <button className="btn primary small" disabled={busy || !label.trim()}>
            Log
          </button>
        </div>
      </form>

      <ol className="ledger">
        {byDay.map((d) => (
          <li key={d.date}>
            <span className="ledger-day muted small">{d.date}</span>
            <ul>
              {d.items.map((e) => (
                <li key={e.id} className={`ledger-row ${e.kind}`}>
                  <span aria-hidden>{SOURCE_ICON[e.source]}</span>
                  <span className="ledger-label">
                    {e.label}
                    {e.source === 'task' && !e.settled && <span className="tag subtle">expected</span>}
                    {e.minutes != null && e.source !== 'sleep' && <span className="muted small"> · {e.minutes} min</span>}
                  </span>
                  <span className={`ledger-amount ${e.kind}`}>{fmtPoints(e.amount)}</span>
                  {(e.source === 'log' || e.source === 'task') && (
                    <button className="icon-btn small" title="Remove (refunds it)" disabled={busy} onClick={() => run(() => api.patienceDelete(e.id))}>
                      ×
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  )
}

const blankTag = (): TagPatience => ({ mode: 'fixed', points: -2, idealMinutes: 30, widthMinutes: 60 })

/** On the Board: each tag's default patience. */
export function TagPatienceEditor({ tags, initial, onClose }: { tags: string[]; initial: Record<string, TagPatience>; onClose: (saved?: Record<string, TagPatience>) => void }) {
  const [rows, setRows] = useState<Record<string, TagPatience>>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const all = useMemo(() => [...new Set([...tags, ...Object.keys(initial)])].sort(), [tags, initial])

  const put = (t: string, p: Partial<TagPatience> | null) =>
    setRows((r) => {
      const next = { ...r }
      if (p === null) delete next[t]
      else next[t] = { ...(r[t] ?? blankTag()), ...p }
      return next
    })

  const save = async () => {
    setBusy(true)
    try {
      onClose(await api.setPatienceTags(rows))
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={() => onClose()}>
      <div className="modal tag-patience" onClick={(e) => e.stopPropagation()}>
        <h2>Patience by tag</h2>
        <p className="muted small">
          The default for a task's check-in comes from its cards' tags. <b>Costs or gives</b> is the same every time (school, work, routines
          cost). A <b>want or need</b> follows a parabola: it gives the most at its climax, then you get accustomed to it and it starts
          costing you. Keep the stretch wide for things like eating, and tight for things that can turn into addictions.
        </p>
        {error && <div className="banner error">{error}</div>}
        {all.length === 0 && <p className="muted">Add tags to your cards first.</p>}
        <ul className="tag-rows">
          {all.map((t) => {
            const p = rows[t]
            return (
              <li key={t} className="tag-row">
                <span className="tag subtle">#{t}</span>
                <select
                  value={p ? p.mode : ''}
                  onChange={(e) => put(t, e.target.value ? { mode: e.target.value as TagPatience['mode'], ...(e.target.value === 'parabola' && !p ? { points: 2 } : {}) } : null)}
                >
                  <option value="">No default</option>
                  <option value="fixed">Costs or gives</option>
                  <option value="parabola">Want or need</option>
                </select>
                {p && (
                  <label className="inline">
                    {p.mode === 'parabola' ? 'Peak' : 'Points'}
                    <input type="number" step={0.5} value={p.points} onChange={(e) => put(t, { points: Number(e.target.value) || 0 })} />
                  </label>
                )}
                {p?.mode === 'parabola' && (
                  <>
                    <label className="inline">
                      Climax at
                      <input type="number" min={1} value={p.idealMinutes} onChange={(e) => put(t, { idealMinutes: Math.max(1, Number(e.target.value) || 1) })} />
                      min
                    </label>
                    <label className="inline">
                      Stretch
                      <input type="number" min={1} value={p.widthMinutes} onChange={(e) => put(t, { widthMinutes: Math.max(1, Number(e.target.value) || 1) })} />
                      min
                    </label>
                    <span className="muted small tag-curve">{curveText(p)}</span>
                  </>
                )}
              </li>
            )
          })}
        </ul>
        <div className="modal-actions">
          <span className="spacer" />
          <button className="btn ghost" onClick={() => onClose()} disabled={busy}>
            Cancel
          </button>
          <button className="btn primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
