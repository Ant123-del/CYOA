import { useState } from 'react'
import { api } from '../lib/api'
import type { DayPlan } from '../types'
import { timelineLabel } from './Adventure'

const PRESETS = [
  'My commute is about 10 minutes - add travel time between places.',
  "I'm running about 30 minutes late - shift what's left.",
  'This feels like too much - make it lighter.',
  'Move my workout to the evening.',
]

/**
 * Work on a day with the AI: feedback in, small edits + a reply out (much cheaper than
 * regenerating). Scope it to one timeline, or rewrite a single timeline from scratch.
 */
export default function RevisePanel({ plan, onPlan }: { plan: DayPlan; onPlan: (p: DayPlan) => void }) {
  const timelines = plan.timelines ?? []
  const [scope, setScope] = useState<string>('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<'send' | 'rewrite' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const history = plan.revisions ?? []

  const send = async (rewrite = false) => {
    const feedback = rewrite ? text.trim() || 'Give me a different take on this timeline.' : text.trim()
    if (!feedback) return
    setBusy(rewrite ? 'rewrite' : 'send')
    setError(null)
    try {
      const r = await api.revise(plan.date, feedback, scope || null, rewrite)
      onPlan(r.plan)
      setText('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const name = (id: string | null) => {
    const t = timelines.find((x) => x.id === id)
    return t ? timelineLabel(t) : 'All timelines'
  }

  return (
    <section className="panel revise">
      <h2>✏️ Revise with AI</h2>
      <p className="muted small">
        Tell the planner what's off and it tweaks just that - quicker and cheaper than regenerating the day. Chapters you
        already chose or missed stay as they are, and calendar events keep their times.
      </p>

      {history.length > 0 && (
        <ol className="revise-history">
          {history.slice(-6).map((r) => (
            <li key={r.at}>
              <div className="you-said">
                <span className="muted small">You{timelines.length ? ` · ${name(r.timelineId)}` : ''}</span>
                {r.feedback}
              </div>
              <div className="ai-said">
                <span className="muted small">Planner · {r.applied} change{r.applied === 1 ? '' : 's'}</span>
                {r.reply}
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="revise-presets">
        {PRESETS.map((p) => (
          <button key={p} className="chip" onClick={() => setText(p)} disabled={busy !== null}>
            {p}
          </button>
        ))}
      </div>

      <div className="revise-row">
        {timelines.length > 0 && (
          <label>
            Apply to
            <select value={scope} onChange={(e) => setScope(e.target.value)} disabled={busy !== null}>
              <option value="">All timelines</option>
              {timelines.map((t) => (
                <option key={t.id} value={t.id}>
                  {timelineLabel(t)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="grow">
          Your feedback
          <textarea
            rows={2}
            maxLength={1000}
            placeholder="e.g. The gym closes at 8, and I want lunch after my lecture."
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send()
            }}
          />
        </label>
      </div>
      {error && <p className="error small">{error}</p>}
      <div className="row-actions">
        <button className="btn primary" onClick={() => send()} disabled={busy !== null || !text.trim()}>
          {busy === 'send' ? 'Revising…' : 'Revise'}
        </button>
        {scope && (
          <button className="btn ghost" onClick={() => send(true)} disabled={busy !== null}>
            {busy === 'rewrite' ? 'Rewriting…' : `↻ Rewrite ${name(scope)} from scratch`}
          </button>
        )}
      </div>
    </section>
  )
}
