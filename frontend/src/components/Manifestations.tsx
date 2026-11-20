import { useEffect, useState, type CSSProperties } from 'react'
import { api } from '../lib/api'
import type { Manifestation, ManifestationInput, ManifestationKind } from '../types'

export const KIND_META: Record<ManifestationKind, { label: string; icon: string; blurb: string }> = {
  complicated: {
    label: 'Complicated',
    icon: '🌧',
    blurb: 'Name the problem as it is, and the thoughts that come with it. That alone is acceptance. Then give it words to answer with.',
  },
  goal: {
    label: 'Ultimate goal',
    icon: '🏔',
    blurb: 'The big ones: who you are becoming and where you want your life to go. Keep the evidence that you are already on your way.',
  },
}

export const blankManifestation = (kind: ManifestationKind): ManifestationInput => ({
  kind,
  title: '',
  description: '',
  evidence: [],
  problem: '',
  naturalManifestations: [],
  corrected: '',
  goalId: '',
})

/* ---------- the chain ---------- */

export type Rung = 'pacing' | 'patience' | 'letting-go' | 'believing' | 'acceptance' | 'manifestation' | 'hope'

const RUNGS: Record<Rung, { label: string; hint: string }> = {
  pacing: { label: 'Pacing', hint: 'A day with room to breathe' },
  patience: { label: 'Patience', hint: 'One tiny step toward the big goal' },
  'letting-go': { label: 'Letting go', hint: 'Release what you can’t control' },
  believing: { label: 'Really believing', hint: 'Words you can truly hold' },
  acceptance: { label: 'Acceptance', hint: 'The problem, as it is' },
  manifestation: { label: 'Manifestation', hint: 'Turn toward it' },
  hope: { label: 'Hope', hint: 'Where it all leads' },
}

/**
 * Pacing → Patience → (Letting go → Acceptance) + (Really believing → Manifestation) → Hope.
 * `lit` highlights rungs; `compact` drops the hints (for the check-in).
 */
export function HopeChain({ lit = [], compact = false }: { lit?: Rung[] | 'all'; compact?: boolean }) {
  const on = (r: Rung) => lit === 'all' || lit.includes(r)
  const node = (r: Rung) => (
    <div className={`chain-node ${r}${on(r) ? ' lit' : ''}`}>
      <span className="chain-label">{RUNGS[r].label}</span>
      {!compact && <span className="chain-hint">{RUNGS[r].hint}</span>}
    </div>
  )
  const arrow = <span className="chain-arrow" aria-hidden />
  return (
    <div
      className={`hope-chain${compact ? ' compact' : ''}`}
      role="img"
      aria-label="Pacing leads to patience. Patience leads to letting go and to really believing. Letting go leads to acceptance, really believing leads to manifestation, and both lead to hope."
    >
      {node('pacing')}
      {arrow}
      {node('patience')}
      {arrow}
      <div className="chain-fork">
        <div className="chain-branch">
          {node('letting-go')}
          {arrow}
          {node('acceptance')}
        </div>
        <div className="chain-branch">
          {node('believing')}
          {arrow}
          {node('manifestation')}
        </div>
      </div>
      {arrow}
      {node('hope')}
    </div>
  )
}

/* ---------- forms ---------- */

/** A list added to one line at a time (natural manifestations, goal evidence). */
function ListField({
  id,
  label,
  hint,
  placeholder,
  items,
  draft,
  setDraft,
  onChange,
  tone,
}: {
  id: string
  label: string
  hint: string
  placeholder: string
  items: string[]
  draft: string
  setDraft: (s: string) => void
  onChange: (items: string[]) => void
  tone: ManifestationKind
}) {
  const add = () => {
    const t = draft.trim()
    if (!t) return
    onChange([...items, t])
    setDraft('')
  }
  return (
    <div className="natural-field">
      <label htmlFor={id}>
        {label}
        <span className="muted small">{hint}</span>
      </label>
      {items.length > 0 && (
        <ul className={`natural-list ${tone}`}>
          {items.map((t, i) => (
            <li key={`${i}-${t}`}>
              <span>{t}</span>
              <button type="button" className="icon-btn" aria-label={`Remove "${t}"`} onClick={() => onChange(items.filter((_, j) => j !== i))}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="natural-add">
        <input
          id={id}
          maxLength={300}
          placeholder={items.length ? 'Another one…' : placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button type="button" className="btn ghost small" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
      </div>
    </div>
  )
}

/** Add / edit one complicated manifestation or ultimate goal. */
export function ManifestationForm({
  id,
  initial,
  goals = [],
  onSaved,
  onCancel,
  onDeleted,
}: {
  id: string | null
  initial: ManifestationInput
  goals?: Manifestation[]
  onSaved: (m: Manifestation) => void
  onCancel: () => void
  onDeleted?: (id: string) => void
}) {
  const [data, setData] = useState<ManifestationInput>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState<string[] | null>(null)
  const [beforeSuggest, setBeforeSuggest] = useState('')
  const [draft, setDraft] = useState('')
  const complicated = data.kind === 'complicated'

  // Something typed in the list box but not added yet still counts.
  const withDraft = (items: string[]) => (draft.trim() ? [...items, draft.trim()] : items)

  const suggest = async () => {
    setSuggesting(true)
    setError(null)
    try {
      const res = await api.suggestCorrected(data.title, data.problem, withDraft(data.naturalManifestations))
      if (suggestions === null) setBeforeSuggest(data.corrected)
      setSuggestions(res.suggestions)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSuggesting(false)
    }
  }

  const noneOfThese = () => {
    setData({ ...data, corrected: beforeSuggest })
    setSuggestions(null)
  }

  const save = async () => {
    if (!data.title.trim()) return
    setSaving(true)
    setError(null)
    try {
      const body = complicated
        ? {
            title: data.title.trim(),
            problem: data.problem.trim(),
            naturalManifestations: withDraft(data.naturalManifestations),
            corrected: data.corrected.trim(),
            goalId: data.goalId,
          }
        : { title: data.title.trim(), description: data.description.trim(), evidence: withDraft(data.evidence) }
      const saved = id ? await api.updateManifestation(id, body) : await api.createManifestation({ ...blankManifestation(data.kind), ...body })
      onSaved(saved)
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!id || !onDeleted || !confirm(complicated ? 'Delete this manifestation?' : 'Delete this ultimate goal?')) return
    try {
      await api.deleteManifestation(id)
      onDeleted(id)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <>
      {error && <div className="banner error">{error}</div>}
      <label>
        {complicated ? 'Title' : 'The goal'}
        <input
          autoFocus
          maxLength={120}
          placeholder={complicated ? 'e.g. "Chem midterm"' : 'e.g. "Become a psychiatrist" or "Live in Rome"'}
          value={data.title}
          onChange={(e) => setData({ ...data, title: e.target.value })}
        />
      </label>
      {complicated ? (
        <>
          <label>
            The unbiased problem
            <span className="muted small">The stressor itself, as plainly and fairly as you can put it. Just the facts.</span>
            <textarea
              rows={3}
              maxLength={2000}
              placeholder="e.g. I scored 58% on my chem midterm. The final is in 4 weeks and is worth 40%."
              value={data.problem}
              onChange={(e) => setData({ ...data, problem: e.target.value })}
            />
          </label>
          <ListField
            id="natural-input"
            label="Natural manifestations"
            hint="The thoughts that come along with it, on their own. Add them one at a time."
            placeholder="e.g. I’m not smart enough for this"
            items={data.naturalManifestations}
            draft={draft}
            setDraft={setDraft}
            onChange={(naturalManifestations) => setData({ ...data, naturalManifestations })}
            tone="complicated"
          />
        </>
      ) : (
        <>
          <label>
            Description
            <span className="muted small">What it looks like when you get there, and why it matters to you.</span>
            <textarea
              rows={4}
              maxLength={4000}
              placeholder="e.g. Helping people through the hardest parts of their lives, in my own practice."
              value={data.description}
              onChange={(e) => setData({ ...data, description: e.target.value })}
            />
          </label>
          <ListField
            id="evidence-input"
            label="Progress & gratitude"
            hint="Evidence you're already on your way, or what makes you grateful for where you are. One at a time."
            placeholder="e.g. Got an A in Intro Psych"
            items={data.evidence}
            draft={draft}
            setDraft={setDraft}
            onChange={(evidence) => setData({ ...data, evidence })}
            tone="goal"
          />
        </>
      )}

      {complicated && (
        <div className="corrected-field">
          <label>
            Corrected manifestation
            <span className="muted small">The words you'll repeat to yourself when this shows up.</span>
            <textarea
              rows={2}
              maxLength={600}
              placeholder="e.g. I am learning at my own pace, and today I take one step."
              value={data.corrected}
              onChange={(e) => setData({ ...data, corrected: e.target.value })}
            />
          </label>
          <button
            type="button"
            className="btn ghost small"
            onClick={suggest}
            disabled={suggesting || !data.problem.trim()}
            title={data.problem.trim() ? undefined : 'Write the unbiased problem first'}
          >
            {suggesting ? 'Thinking…' : suggestions ? '✨ Suggest 5 more' : '✨ Suggest 5'}
          </button>
          {suggestions && (
            <div className="suggest-list" role="radiogroup" aria-label="Suggested corrected manifestations">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  role="radio"
                  aria-checked={data.corrected === s}
                  className={`suggest-opt${data.corrected === s ? ' picked' : ''}`}
                  onClick={() => setData({ ...data, corrected: s })}
                >
                  {s}
                </button>
              ))}
              <button type="button" className="suggest-opt none" onClick={noneOfThese}>
                None of these
              </button>
            </div>
          )}
        </div>
      )}

      {complicated && (
        <label>
          Leads toward
          <span className="muted small">The ultimate goal this is closest to. The check-in takes you there after the corrected manifestation.</span>
          <select value={goals.some((g) => g.id === data.goalId) ? data.goalId : ''} onChange={(e) => setData({ ...data, goalId: e.target.value })}>
            <option value="">{goals.length ? 'Choose at the check-in' : 'No ultimate goals yet'}</option>
            {goals.map((g) => (
              <option key={g.id} value={g.id}>
                {KIND_META.goal.icon} {g.title}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="modal-actions">
        {id && onDeleted && (
          <button className="btn danger ghost" onClick={remove}>
            Delete
          </button>
        )}
        <span className="spacer" />
        <button className="btn ghost" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn primary" onClick={save} disabled={saving || !data.title.trim()}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </>
  )
}

/* ---------- pieces shown in the check-in ---------- */

/** The original problem, shown alongside its corrected manifestation. */
export function ProblemNote({ item }: { item: Manifestation }) {
  if (item.kind !== 'complicated' || !item.problem) return null
  return (
    <div className="problem-note">
      <span className="muted small">The original problem</span>
      <p>{item.problem}</p>
    </div>
  )
}

/** An ultimate goal: what it is, and the evidence you're already on your way. */
export function GoalNote({ goal }: { goal: Manifestation }) {
  return (
    <div className="goal-note">
      <span className="muted small">{KIND_META.goal.icon} Your ultimate goal</span>
      <p className="goal-title">{goal.title}</p>
      {goal.description && <p className="goal-desc">{goal.description}</p>}
      {goal.evidence.length > 0 && (
        <ul className="evidence-list">
          {goal.evidence.map((t, i) => (
            <li key={`${i}-${t}`}>{t}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

const BEST_KEY = 'cyoa.trophy.bestCps'
const readBest = () => {
  try {
    return Number(localStorage.getItem(BEST_KEY)) || 0
  } catch {
    return 0
  }
}

export type ClickStats = { clicks: number; seconds: number; cps: number; best: boolean }

/** The tiny step: click the trophy 20-80 times (random), as fast as you can. */
function TrophyClicker({ onDone }: { onDone: (s: ClickStats) => void }) {
  const [target] = useState(() => 20 + Math.floor(Math.random() * 61))
  const [count, setCount] = useState(0)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [bump, setBump] = useState(0)

  const hit = () => {
    if (count >= target) return
    const now = performance.now()
    const start = startedAt ?? now
    if (startedAt === null) setStartedAt(now)
    const next = count + 1
    setCount(next)
    setBump((b) => b + 1)
    if (next === target) {
      const seconds = Math.max((now - start) / 1000, 0.1)
      const cps = next / seconds
      const best = cps > readBest()
      if (best) {
        try {
          localStorage.setItem(BEST_KEY, String(cps))
        } catch {
          /* best score just isn't remembered */
        }
      }
      setTimeout(() => onDone({ clicks: next, seconds, cps, best }), 250)
    }
  }

  const left = target - count
  return (
    <div className="trophy-zone">
      <button
        type="button"
        className="trophy-btn"
        style={{ '--p': count / target } as CSSProperties}
        onClick={hit}
        onKeyDown={(e) => e.repeat && e.preventDefault()} // no holding Enter down
        aria-label={`Trophy: ${left} clicks to go`}
      >
        <span key={bump} className="trophy-icon" aria-hidden>
          🏆
        </span>
      </button>
      <p className="trophy-count" aria-live="polite">
        {count === 0 ? (
          <>
            Click the trophy <strong>{target}</strong> times, as fast as you can.
          </>
        ) : left > 0 ? (
          <>
            <strong>{left}</strong> to go
          </>
        ) : (
          'Done!'
        )}
      </p>
    </div>
  )
}

/* ---------- the check-in ---------- */

type Step =
  | { name: 'feeling' }
  | { name: 'list'; kind: ManifestationKind }
  | { name: 'form'; kind: ManifestationKind; item: Manifestation | null; from: Manifestation | null }
  | { name: 'show'; item: Manifestation }
  | { name: 'pick-goal'; from: Manifestation | null }
  | { name: 'goal'; goal: Manifestation; from: Manifestation | null }
  | { name: 'manifested'; goal: Manifestation; from: Manifestation | null; stats: ClickStats }

const STEP_RUNGS: Record<Step['name'], Rung[] | 'all'> = {
  feeling: ['pacing'],
  list: ['pacing'],
  form: ['letting-go', 'acceptance'],
  show: ['acceptance', 'manifestation'],
  'pick-goal': ['patience'],
  goal: ['patience'],
  manifested: 'all',
}

/**
 * Asked before choosing a path: which manifestations are feeding into you right now?
 * A complicated one shows its problem and corrected manifestation, then goes on to its
 * ultimate goal, where you click the trophy (the tiny step) until it's "Manifested".
 */
export function HopeCheckIn({
  taskTitle,
  onContinue,
  onCancel,
  context = 'Before you start',
  continueLabel = 'Continue →',
}: {
  taskTitle: string
  /** The complicated manifestation you checked in with (if any), and the goal it led to. */
  onContinue: (item: Manifestation | null, goal: Manifestation | null) => void
  onCancel: () => void
  context?: string
  continueLabel?: string
}) {
  const [items, setItems] = useState<Manifestation[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState<Step>({ name: 'feeling' })

  useEffect(() => {
    api
      .manifestations()
      .then(setItems)
      .catch((e) => {
        setError(e.message)
        setItems([])
      })
  }, [])

  const goals = (items ?? []).filter((m) => m.kind === 'goal')
  const put = (m: Manifestation) => setItems((xs) => [m, ...(xs ?? []).filter((x) => x.id !== m.id)])

  /** After a complicated one: its linked goal, or ask which one it leads toward. */
  const toGoal = (from: Manifestation) => {
    const linked = goals.find((g) => g.id === from.goalId)
    setStep(linked ? { name: 'goal', goal: linked, from } : { name: 'pick-goal', from })
  }

  /** Remember which goal a complicated one leads toward, so next time it goes straight there. */
  const link = (from: Manifestation | null, goal: Manifestation) => {
    if (from && from.goalId !== goal.id) {
      put({ ...from, goalId: goal.id })
      api.updateManifestation(from.id, { goalId: goal.id }).then(put).catch((e) => setError(e.message))
    }
    setStep({ name: 'goal', goal, from: from ? { ...from, goalId: goal.id } : null })
  }

  const onFormSaved = (m: Manifestation, from: Manifestation | null) => {
    put(m)
    if (m.kind === 'goal') link(from, m)
    else setStep({ name: 'show', item: m })
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal hope-checkin" onClick={(e) => e.stopPropagation()}>
        <div className="checkin-head">
          <span className="muted small">
            {context}: {taskTitle}
          </span>
          <button className="btn ghost small" onClick={() => onContinue(null, null)}>
            Skip
          </button>
        </div>
        <HopeChain compact lit={step.name === 'form' && step.kind === 'goal' ? ['patience'] : STEP_RUNGS[step.name]} />
        {error && <div className="banner error">{error}</div>}

        {step.name === 'feeling' && (
          <>
            <h2>What manifestations do you feel feeding into you?</h2>
            <div className="feeling-row">
              {(['complicated', 'goal'] as const).map((k) => (
                <button key={k} className={`feeling-btn ${k}`} onClick={() => setStep({ name: 'list', kind: k })}>
                  <span className="feeling-icon" aria-hidden>
                    {KIND_META[k].icon}
                  </span>
                  {KIND_META[k].label}
                </button>
              ))}
            </div>
          </>
        )}

        {step.name === 'list' && (
          <>
            <h2>
              {KIND_META[step.kind].icon} Which {step.kind === 'goal' ? 'ultimate goal' : 'complicated one'}?
            </h2>
            {items === null ? (
              <p className="muted">Loading…</p>
            ) : (
              <div className="checkin-list">
                {items
                  .filter((m) => m.kind === step.kind)
                  .map((m) => (
                    <button
                      key={m.id}
                      className="checkin-item"
                      onClick={() => setStep(m.kind === 'goal' ? { name: 'goal', goal: m, from: null } : { name: 'show', item: m })}
                    >
                      {m.title}
                    </button>
                  ))}
                <button className="checkin-item new" onClick={() => setStep({ name: 'form', kind: step.kind, item: null, from: null })}>
                  New +
                </button>
              </div>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setStep({ name: 'feeling' })}>
                ‹ Back
              </button>
            </div>
          </>
        )}

        {step.name === 'form' && (
          <>
            <h2>
              {step.item ? 'Edit' : 'New'} {step.kind === 'goal' ? 'ultimate goal' : 'complicated manifestation'}
            </h2>
            <ManifestationForm
              id={step.item?.id ?? null}
              initial={step.item ?? blankManifestation(step.kind)}
              goals={goals}
              onSaved={(m) => onFormSaved(m, step.from)}
              onCancel={() =>
                step.item
                  ? setStep({ name: 'show', item: step.item })
                  : step.kind === 'goal' && step.from
                    ? setStep({ name: 'pick-goal', from: step.from })
                    : setStep({ name: 'list', kind: step.kind })
              }
            />
          </>
        )}

        {step.name === 'show' && (
          <>
            <h2>{step.item.title}</h2>
            <ProblemNote item={step.item} />
            {step.item.corrected ? (
              <div className="mantra">
                <span className="muted small">Repeat to yourself</span>
                <p>{step.item.corrected}</p>
              </div>
            ) : (
              <div className="mantra empty-mantra">
                <p className="muted">There's no corrected manifestation for this one yet.</p>
                <button className="btn ghost small" onClick={() => setStep({ name: 'form', kind: 'complicated', item: step.item, from: null })}>
                  Write one
                </button>
              </div>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setStep({ name: 'list', kind: 'complicated' })}>
                ‹ Back
              </button>
              <span className="spacer" />
              <button className="btn primary" onClick={() => toGoal(step.item)}>
                Toward your goal →
              </button>
            </div>
          </>
        )}

        {step.name === 'pick-goal' && (
          <>
            <h2>{KIND_META.goal.icon} Which ultimate goal does this lead toward?</h2>
            {step.from && <p className="muted small">CYOA will remember it for “{step.from.title}”.</p>}
            <div className="checkin-list">
              {goals.map((g) => (
                <button key={g.id} className="checkin-item" onClick={() => link(step.from, g)}>
                  {g.title}
                </button>
              ))}
              <button className="checkin-item new" onClick={() => setStep({ name: 'form', kind: 'goal', item: null, from: step.from })}>
                New +
              </button>
            </div>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => (step.from ? setStep({ name: 'show', item: step.from }) : setStep({ name: 'feeling' }))}>
                ‹ Back
              </button>
              <span className="spacer" />
              <button className="btn ghost" onClick={() => onContinue(step.from, null)}>
                Continue without one
              </button>
            </div>
          </>
        )}

        {step.name === 'goal' && (
          <>
            <GoalNote goal={step.goal} />
            <TrophyClicker key={step.goal.id} onDone={(stats) => setStep({ name: 'manifested', goal: step.goal, from: step.from, stats })} />
            <div className="modal-actions">
              <button
                className="btn ghost"
                onClick={() => (step.from ? setStep({ name: 'show', item: step.from }) : setStep({ name: 'list', kind: 'goal' }))}
              >
                ‹ Back
              </button>
              {step.from && (
                <button className="btn ghost small" onClick={() => setStep({ name: 'pick-goal', from: step.from })}>
                  Different goal
                </button>
              )}
            </div>
          </>
        )}

        {step.name === 'manifested' && (
          <>
            <div className="manifested">
              <span className="manifested-icon" aria-hidden>
                🏆
              </span>
              <h2>Manifested</h2>
              <p className="muted">
                {step.stats.clicks} clicks in {step.stats.seconds.toFixed(1)}s · {step.stats.cps.toFixed(1)} per second
                {step.stats.best && <strong className="best"> · New best!</strong>}
              </p>
              <p className="manifested-goal">One tiny step closer to {step.goal.title}.</p>
            </div>
            <div className="modal-actions">
              <span className="spacer" />
              <button className="btn primary" onClick={() => onContinue(step.from, step.goal)}>
                {continueLabel}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
