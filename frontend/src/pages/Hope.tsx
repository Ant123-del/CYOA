import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { KIND_META, ManifestationForm, blankManifestation } from '../components/Manifestations'
import type { Manifestation, ManifestationInput, ManifestationKind } from '../types'

export default function Hope() {
  const [items, setItems] = useState<Manifestation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: string | null; data: ManifestationInput } | null>(null)

  useEffect(() => {
    api
      .manifestations()
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const onSaved = (m: Manifestation) => {
    setItems((xs) => (xs.some((x) => x.id === m.id) ? xs.map((x) => (x.id === m.id ? m : x)) : [m, ...xs]))
    setEditing(null)
  }

  const onDeleted = (id: string) => {
    setItems((xs) => xs.filter((x) => x.id !== id))
    setEditing(null)
  }

  const section = (kind: ManifestationKind) => {
    const list = items.filter((m) => m.kind === kind)
    return (
      <section className={`hope-col ${kind}`}>
        <div className="hope-col-head">
          <h2>
            <span aria-hidden>{KIND_META[kind].icon}</span> {KIND_META[kind].label} manifestations
          </h2>
          <button className="btn ghost small" onClick={() => setEditing({ id: null, data: blankManifestation(kind) })}>
            New +
          </button>
        </div>
        <p className="muted small">{KIND_META[kind].blurb}</p>
        {!loading && list.length === 0 && <p className="muted small hope-empty">Nothing here yet.</p>}
        <ul className="hope-list">
          {list.map((m) => (
            <li key={m.id}>
              <button
                className="hope-card"
                onClick={() => setEditing({ id: m.id, data: { kind: m.kind, title: m.title, description: m.description, corrected: m.corrected } })}
              >
                <span className="hope-title">{m.title}</span>
                {m.description && <span className="hope-desc">{m.description}</span>}
                {kind === 'negative' &&
                  (m.corrected ? (
                    <span className="hope-corrected">
                      <span className="muted small">Corrected</span>
                      {m.corrected}
                    </span>
                  ) : (
                    <span className="muted small">No corrected manifestation yet</span>
                  ))}
              </button>
            </li>
          ))}
        </ul>
      </section>
    )
  }

  return (
    <div className="page hope">
      <div className="page-head">
        <div>
          <h1>Hope</h1>
          <p className="muted">Accept what's in your head, then answer it. Before each choice on Today, you'll check in with these.</p>
        </div>
      </div>
      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      {loading && <p className="muted">Loading…</p>}
      <div className="hope-grid">
        {section('negative')}
        {section('positive')}
      </div>

      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>
              {editing.id ? 'Edit' : 'New'} {editing.data.kind} manifestation
            </h2>
            <ManifestationForm
              id={editing.id}
              initial={editing.data}
              onSaved={onSaved}
              onCancel={() => setEditing(null)}
              onDeleted={onDeleted}
            />
          </div>
        </div>
      )}
    </div>
  )
}
