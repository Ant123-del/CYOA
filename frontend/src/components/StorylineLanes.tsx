import type { CSSProperties } from 'react'
import { fmtTime } from '../lib/dates'
import type { Chapter, DayPlan, Option } from '../types'
import { KindBadge, SourceTag } from './Adventure'

/**
 * The day as parallel routes: one column per storyline, one row per chapter. Each cell is
 * what that storyline does in that chapter, so you can read a storyline top-to-bottom like
 * its own story - and switch columns whenever the day changes. Options that belong to no
 * storyline (e.g. plain "Yes, go") show under the chapter title.
 */
export default function StorylineLanes({
  plan,
  activeId,
  busy,
  onChoose,
}: {
  plan: DayPlan
  activeId?: string | null
  busy?: string | null
  onChoose?: (chapter: Chapter, optionId: string) => void
}) {
  const storylines = plan.storylines
  if (!storylines.length) {
    return <p className="muted">This plan has no storylines yet - add some on the Plan page, or generate the day with AI.</p>
  }
  const ids = new Set(storylines.map((s) => s.id))

  const cell = (c: Chapter, o: Option) => {
    const picked = c.chosenOptionId === o.id
    const otherPicked = Boolean(c.chosenOptionId) && !picked
    const content = (
      <>
        {o.kind !== 'route' && <KindBadge option={o} storylines={[]} />}
        <span className="lane-title">{o.title}</span>
        {o.detail && <span className="lane-detail">{o.detail}</span>}
        {o.durationMinutes ? <span className="lane-mins">{o.durationMinutes} min</span> : null}
      </>
    )
    const cls = `lane-option${picked ? ' picked' : ''}${otherPicked ? ' faded' : ''}`
    return onChoose && !c.chosenOptionId ? (
      <button key={o.id} className={cls} onClick={() => onChoose(c, o.id)} disabled={busy != null}>
        {content}
        <span className="lane-go">{busy === o.id ? 'Scheduling…' : 'Choose →'}</span>
      </button>
    ) : (
      <div key={o.id} className={cls}>
        {content}
        {picked && <span className="lane-go">Chosen ✓</span>}
      </div>
    )
  }

  return (
    <div className="lanes-scroll">
      <div className="lanes" style={{ '--lanes': storylines.length } as CSSProperties}>
        <div className="lane-head lane-corner">Chapter</div>
        {storylines.map((s) => (
          <div key={s.id} className="lane-head" style={{ '--c': s.color ?? 'var(--accent)' } as CSSProperties}>
            <span className="lane-name">{s.name}</span>
            {s.description && <span className="lane-desc">{s.description}</span>}
          </div>
        ))}

        {plan.chapters.map((c) => {
          const shared = c.options.filter((o) => !o.storylineId || !ids.has(o.storylineId))
          return (
            <div key={c.id} className={`lane-row${c.id === activeId ? ' active' : ''}`}>
              <div className="lane-chapter">
                <span className="lane-time">
                  {fmtTime(c.start)} – {fmtTime(c.end)}
                </span>
                <span className="lane-chapter-title">{c.title}</span>
                <SourceTag chapter={c} />
                {shared.length > 0 && <div className="lane-shared">{shared.map((o) => cell(c, o))}</div>}
              </div>
              {storylines.map((s) => {
                const opts = c.options.filter((o) => o.storylineId === s.id)
                return (
                  <div key={s.id} className="lane-cell" style={{ '--c': s.color ?? 'var(--accent)' } as CSSProperties}>
                    {opts.length ? opts.map((o) => cell(c, o)) : <span className="lane-empty">—</span>}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}
