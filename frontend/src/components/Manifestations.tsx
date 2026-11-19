import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Manifestation, ManifestationInput, ManifestationKind } from '../types'

export const KIND_META: Record<ManifestationKind, { label: string; icon: string; blurb: string }> = {
  complicated: {
    label: 'Complicated',
    icon: '🌧',
    blurb: 'Name the problem as it is, and the thoughts that come with it. That alone is acceptance. Then give it words to answer with.',
  },
  positive: {
    label: 'Positive',
    icon: '🌤',
    blurb: 'What lifts you up. Keep it close so you can come back to it.',
  },
}

export const blankManifestation = (kind: ManifestationKind): ManifestationInput => ({
  kind,
  title: '',
  description: '',
  problem: '',
  naturalManifestations: [],
  corrected: '',
})

/** Add / edit one manifestation. Negative ones get a corrected manifestation, with AI suggestions. */
export function ManifestationForm({
  id,
  initial,
  onSaved,
  onCancel,
  onDeleted,
}: {
  id: string | null
  initial: ManifestationInput
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
  const [natural, setNatural] = useState('')
  const complicated = data.kind === 'complicated'

  const addNatural = () => {
    const t = natural.trim()
    if (!t) return
    setData({ ...data, naturalManifestations: [...data.naturalManifestations, t] })
    setNatural('')
  }
  const removeNatural = (i: number) =>
    setData({ ...data, naturalManifestations: data.naturalManifestations.filter((_, j) => j !== i) })

  const suggest = async () => {
    setSuggesting(true)
    setError(null)
    try {
      const res = await api.suggestCorrected(data.title, data.problem, pendingNaturals())
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

  // Something typed in the natural-manifestation box but not added yet still counts.
  const pendingNaturals = () => (natural.trim() ? [...data.naturalManifestations, natural.trim()] : data.naturalManifestations)

  const save = async () => {
    if (!data.title.trim()) return
    setSaving(true)
    setError(null)
    try {
      const body = complicated
        ? { title: data.title.trim(), problem: data.problem.trim(), naturalManifestations: pendingNaturals(), corrected: data.corrected.trim() }
        : { title: data.title.trim(), description: data.description.trim() }
      const saved = id ? await api.updateManifestation(id, body) : await api.createManifestation({ ...blankManifestation(data.kind), ...body })
      onSaved(saved)
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!id || !onDeleted || !confirm('Delete this manifestation?')) return
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
        Title
        <input
          autoFocus
          maxLength={120}
          placeholder={complicated ? 'e.g. "Chem midterm"' : 'e.g. "I finished the hard thing"'}
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
          <div className="natural-field">
            <label htmlFor="natural-input">
              Natural manifestations
              <span className="muted small">The thoughts that come along with it, on their own. Add them one at a time.</span>
            </label>
            {data.naturalManifestations.length > 0 && (
              <ul className="natural-list">
                {data.naturalManifestations.map((t, i) => (
                  <li key={`${i}-${t}`}>
                    <span>{t}</span>
                    <button type="button" className="icon-btn" aria-label={`Remove "${t}"`} onClick={() => removeNatural(i)}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="natural-add">
              <input
                id="natural-input"
                maxLength={300}
                placeholder={data.naturalManifestations.length ? 'Another one…' : 'e.g. I’m not smart enough for this'}
                value={natural}
                onChange={(e) => setNatural(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    addNatural()
                  }
                }}
              />
              <button type="button" className="btn ghost small" onClick={addNatural} disabled={!natural.trim()}>
                Add
              </button>
            </div>
          </div>
        </>
      ) : (
        <label>
          Description
          <textarea
            rows={4}
            maxLength={4000}
            placeholder="What happened, and how did it feel?"
            value={data.description}
            onChange={(e) => setData({ ...data, description: e.target.value })}
          />
        </label>
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

type Step =
  | { name: 'feeling' }
  | { name: 'list'; kind: ManifestationKind }
  | { name: 'show'; item: Manifestation }
  | { name: 'form'; kind: ManifestationKind; item: Manifestation | null }

/** Asked before choosing a path: which manifestations are feeding into you right now? */
export function HopeCheckIn({
  taskTitle,
  onContinue,
  onCancel,
}: {
  taskTitle: string
  onContinue: () => void
  onCancel: () => void
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

  const upsert = (m: Manifestation) => {
    setItems((xs) => [m, ...(xs ?? []).filter((x) => x.id !== m.id)])
    setStep({ name: 'show', item: m })
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal hope-checkin" onClick={(e) => e.stopPropagation()}>
        <div className="checkin-head">
          <span className="muted small">Before you start: {taskTitle}</span>
          <button className="btn ghost small" onClick={onContinue}>
            Skip
          </button>
        </div>
        {error && <div className="banner error">{error}</div>}

        {step.name === 'feeling' && (
          <>
            <h2>What manifestations do you feel feeding into you?</h2>
            <div className="feeling-row">
              {(['positive', 'complicated'] as const).map((k) => (
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
              {KIND_META[step.kind].icon} Which {KIND_META[step.kind].label.toLowerCase()} one?
            </h2>
            {items === null ? (
              <p className="muted">Loading…</p>
            ) : (
              <div className="checkin-list">
                {items
                  .filter((m) => m.kind === step.kind)
                  .map((m) => (
                    <button key={m.id} className="checkin-item" onClick={() => setStep({ name: 'show', item: m })}>
                      {m.title}
                    </button>
                  ))}
                <button className="checkin-item new" onClick={() => setStep({ name: 'form', kind: step.kind, item: null })}>
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
              {step.item ? 'Edit' : 'New'} {KIND_META[step.kind].label.toLowerCase()} manifestation
            </h2>
            <ManifestationForm
              id={step.item?.id ?? null}
              initial={step.item ?? blankManifestation(step.kind)}
              onSaved={upsert}
              onCancel={() => (step.item ? setStep({ name: 'show', item: step.item }) : setStep({ name: 'list', kind: step.kind }))}
            />
          </>
        )}

        {step.name === 'show' && (
          <>
            <h2>{step.item.title}</h2>
            {step.item.kind === 'complicated' ? (
              step.item.corrected ? (
                <div className="mantra">
                  <span className="muted small">Repeat to yourself</span>
                  <p>{step.item.corrected}</p>
                </div>
              ) : (
                <div className="mantra empty-mantra">
                  <p className="muted">There's no corrected manifestation for this one yet.</p>
                  <button className="btn ghost small" onClick={() => setStep({ name: 'form', kind: 'complicated', item: step.item })}>
                    Write one
                  </button>
                </div>
              )
            ) : (
              <div className="mantra positive">
                <span className="muted small">Let this feed you</span>
                <p>{step.item.description || step.item.title}</p>
              </div>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setStep({ name: 'list', kind: step.item.kind })}>
                ‹ Back
              </button>
              <span className="spacer" />
              <button className="btn primary" onClick={onContinue}>
                Continue →
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
