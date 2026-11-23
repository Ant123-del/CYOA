import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { TagPatienceEditor } from '../components/Patience'
import type { Goal, GoalInput, GoalStatus, Priority } from '../types'

const COLUMNS: { id: GoalStatus; title: string; hint: string }[] = [
  { id: 'backlog', title: 'Backlog', hint: 'Someday ideas' },
  { id: 'todo', title: 'To do', hint: 'Ready for an adventure' },
  { id: 'doing', title: 'Doing', hint: 'In progress' },
  { id: 'done', title: 'Done', hint: 'Victories' },
]

const PRIORITY_LABEL: Record<Priority, string> = { high: 'High', medium: 'Medium', low: 'Low' }

const blankGoal = (status: GoalStatus): GoalInput => ({
  title: '',
  description: '',
  status,
  priority: 'medium',
  estimateMinutes: null,
  dueDate: null,
  tags: [],
  order: Date.now(),
})

export default function Board() {
  const [goals, setGoals] = useState<Goal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: string | null; data: GoalInput } | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overCol, setOverCol] = useState<GoalStatus | null>(null)
  const [quickAdd, setQuickAdd] = useState<Record<string, string>>({})
  const [tagPatience, setTagPatience] = useState(false)
  const { settings, setSettings } = useAuth()
  const allTags = useMemo(() => [...new Set(goals.flatMap((g) => g.tags))], [goals])

  useEffect(() => {
    api
      .goals()
      .then(setGoals)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const byColumn = useMemo(() => {
    const map: Record<GoalStatus, Goal[]> = { backlog: [], todo: [], doing: [], done: [] }
    for (const g of goals) map[g.status]?.push(g)
    for (const k of Object.keys(map) as GoalStatus[]) map[k].sort((a, b) => a.order - b.order)
    return map
  }, [goals])

  const move = async (id: string, status: GoalStatus, beforeId: string | null) => {
    const col = byColumn[status].filter((g) => g.id !== id)
    const idx = beforeId ? col.findIndex((g) => g.id === beforeId) : col.length
    const prev = col[idx - 1]?.order ?? (col[0]?.order ?? Date.now()) - 1000
    const next = col[idx]?.order ?? prev + 2000
    const order = (prev + next) / 2
    setGoals((gs) => gs.map((g) => (g.id === id ? { ...g, status, order } : g)))
    try {
      await api.updateGoal(id, { status, order })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const save = async () => {
    if (!editing || !editing.data.title.trim()) return
    try {
      if (editing.id) {
        const updated = await api.updateGoal(editing.id, editing.data)
        setGoals((gs) => gs.map((g) => (g.id === updated.id ? updated : g)))
      } else {
        const created = await api.createGoal(editing.data)
        setGoals((gs) => [...gs, created])
      }
      setEditing(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async (id: string) => {
    setGoals((gs) => gs.filter((g) => g.id !== id))
    setEditing(null)
    await api.deleteGoal(id).catch((e) => setError(e.message))
  }

  const quickCreate = async (status: GoalStatus) => {
    const title = (quickAdd[status] ?? '').trim()
    if (!title) return
    setQuickAdd((q) => ({ ...q, [status]: '' }))
    try {
      const created = await api.createGoal({ ...blankGoal(status), title })
      setGoals((gs) => [...gs, created])
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Quest board</h1>
          <p className="muted">Everything you want to do. The planner pulls from <b>To do</b> and <b>Doing</b>.</p>
        </div>
        <div className="head-actions">
          <button className="btn ghost" onClick={() => setTagPatience(true)}>
            ⏳ Patience by tag
          </button>
          <button className="btn primary" onClick={() => setEditing({ id: null, data: blankGoal('todo') })}>
            + New goal
          </button>
        </div>
      </div>
      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="board">
          {COLUMNS.map((col) => (
            <section
              key={col.id}
              className={`column${overCol === col.id ? ' over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setOverCol(col.id)
              }}
              onDragLeave={() => setOverCol(null)}
              onDrop={(e) => {
                e.preventDefault()
                setOverCol(null)
                if (dragId) move(dragId, col.id, null)
                setDragId(null)
              }}
            >
              <header className="column-head">
                <h2>{col.title}</h2>
                <span className="count">{byColumn[col.id].length}</span>
              </header>
              <p className="column-hint">{col.hint}</p>
              <div className="cards">
                {byColumn[col.id].map((g) => (
                  <article
                    key={g.id}
                    className={`goal-card prio-${g.priority}${dragId === g.id ? ' dragging' : ''}`}
                    draggable
                    onDragStart={(e) => {
                      setDragId(g.id)
                      e.dataTransfer.effectAllowed = 'move'
                    }}
                    onDragEnd={() => setDragId(null)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setOverCol(null)
                      if (dragId && dragId !== g.id) move(dragId, col.id, g.id)
                      setDragId(null)
                    }}
                    onClick={() => setEditing({ id: g.id, data: { ...g } })}
                  >
                    <div className="goal-title">{g.title}</div>
                    {g.description && <div className="goal-desc">{g.description}</div>}
                    <div className="goal-meta">
                      <span className={`tag prio prio-${g.priority}`}>{PRIORITY_LABEL[g.priority]}</span>
                      {g.estimateMinutes ? (
                        <span className="tag" title="Rough total effort - CYOA spreads it over several days">
                          ⏱ ~{g.estimateMinutes}m total
                        </span>
                      ) : null}
                      {g.dueDate ? <span className="tag">📅 {g.dueDate}</span> : null}
                      {g.tags.map((t) => {
                        const p = settings?.patienceTags?.[t]
                        return (
                          <span key={t} className="tag subtle" title={p ? (p.mode === 'parabola' ? 'Want or need' : 'Default patience') : undefined}>
                            #{t}
                            {p && <span className={p.points >= 0 ? 'emission' : 'absorption'}> {p.points > 0 ? '+' : ''}{p.points}{p.mode === 'parabola' ? '⌒' : ''}</span>}
                          </span>
                        )
                      })}
                    </div>
                  </article>
                ))}
              </div>
              <form
                className="quick-add"
                onSubmit={(e) => {
                  e.preventDefault()
                  quickCreate(col.id)
                }}
              >
                <input
                  placeholder="+ Add a card"
                  value={quickAdd[col.id] ?? ''}
                  onChange={(e) => setQuickAdd((q) => ({ ...q, [col.id]: e.target.value }))}
                />
              </form>
            </section>
          ))}
        </div>
      )}

      {tagPatience && (
        <TagPatienceEditor
          tags={allTags}
          initial={settings?.patienceTags ?? {}}
          onClose={(saved) => {
            setTagPatience(false)
            if (saved && settings) setSettings({ ...settings, patienceTags: saved })
          }}
        />
      )}

      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editing.id ? 'Edit goal' : 'New goal'}</h2>
            <label>
              Title
              <input
                autoFocus
                value={editing.data.title}
                onChange={(e) => setEditing({ ...editing, data: { ...editing.data, title: e.target.value } })}
              />
            </label>
            <label>
              Description
              <textarea
                rows={3}
                value={editing.data.description}
                onChange={(e) => setEditing({ ...editing, data: { ...editing.data, description: e.target.value } })}
              />
            </label>
            <div className="row">
              <label>
                Priority
                <select
                  value={editing.data.priority}
                  onChange={(e) =>
                    setEditing({ ...editing, data: { ...editing.data, priority: e.target.value as Priority } })
                  }
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </label>
              <label>
                Column
                <select
                  value={editing.data.status}
                  onChange={(e) =>
                    setEditing({ ...editing, data: { ...editing.data, status: e.target.value as GoalStatus } })
                  }
                >
                  {COLUMNS.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="row">
              <label>
                Total effort, roughly (minutes - spread over days)
                <input
                  type="number"
                  min={0}
                  value={editing.data.estimateMinutes ?? ''}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      data: { ...editing.data, estimateMinutes: e.target.value ? Number(e.target.value) : null },
                    })
                  }
                />
              </label>
              <label>
                Due date
                <input
                  type="date"
                  value={editing.data.dueDate ?? ''}
                  onChange={(e) =>
                    setEditing({ ...editing, data: { ...editing.data, dueDate: e.target.value || null } })
                  }
                />
              </label>
            </div>
            <label>
              Tags (comma separated)
              <input
                value={editing.data.tags.join(', ')}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    data: {
                      ...editing.data,
                      tags: e.target.value
                        .split(',')
                        .map((t) => t.trim())
                        .filter(Boolean),
                    },
                  })
                }
              />
            </label>
            <div className="modal-actions">
              {editing.id && (
                <button className="btn danger ghost" onClick={() => remove(editing.id!)}>
                  Delete
                </button>
              )}
              <span className="spacer" />
              <button className="btn ghost" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="btn primary" onClick={save} disabled={!editing.data.title.trim()}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
