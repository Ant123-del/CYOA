import type { CSSProperties } from 'react'
import { fmtTime } from '../lib/dates'
import { activity, currentTimeline, cutoff, doneActivities } from '../lib/path'
import type { Chapter, DayPlan } from '../types'
import { KindBadge, ROLE_LABEL, SourceTag, SwitchTag, calendarNote, optionColor, timelineLabel } from './Adventure'

/**
 * Every version of the day side by side - one column per timeline. Your path is
 * highlighted: what you chose, and what's ahead on the timeline you're on. Each option
 * shows the storyline it belongs to and, if it switches, which timeline it leads to.
 */
export default function TimelineMap({
  plan,
  busy,
  onChoose,
}: {
  plan: DayPlan
  busy?: string | null
  onChoose?: (chapter: Chapter, optionId: string) => void
}) {
  const timelines = plan.timelines ?? []
  const here = currentTimeline(plan)
  const done = doneActivities(plan)
  const cut = cutoff(plan)

  const status = (c: Chapter) => {
    if (c.chosenOptionId) return 'chosen'
    if (done.has(activity(c))) return 'done-elsewhere'
    if (c.timelineId === here?.id && c.start >= cut) return 'ahead'
    if (c.start < cut) return 'passed'
    return 'alternative'
  }

  return (
    <div className="lanes-scroll">
      <div className="tmap" style={{ '--cols': timelines.length } as CSSProperties}>
        {timelines.map((t) => {
          const chapters = plan.chapters.filter((c) => c.timelineId === t.id).sort((a, b) => a.start.localeCompare(b.start))
          return (
            <section key={t.id} className={`tmap-col${t.id === here?.id ? ' here' : ''}`} style={{ '--c': t.color ?? 'var(--accent)' } as CSSProperties}>
              <header className="tmap-head">
                <div className="tmap-name">
                  {timelineLabel(t)}
                  {t.id === here?.id && <span className="you-pill">You're here</span>}
                </div>
                {t.role && <p className="tmap-role">{ROLE_LABEL[t.role]}</p>}
                {t.description && <p className="tmap-desc">{t.description}</p>}
                <p className="tmap-skips">
                  {calendarNote(t)}
                </p>
              </header>
              {chapters.map((c) => {
                const st = status(c)
                const canChoose = onChoose && (st === 'ahead' || st === 'alternative')
                return (
                  <article key={c.id} className={`tmap-ch ${st}`}>
                    <div className="tmap-ch-head">
                      <span className="lane-time">
                        {fmtTime(c.start)} – {fmtTime(c.end)}
                      </span>
                      <SourceTag chapter={c} />
                      {st === 'done-elsewhere' && <span className="tag subtle">Done</span>}
                    </div>
                    <div className="tmap-ch-title">{c.title}</div>
                    <div className="tmap-opts">
                      {c.options.map((o) => {
                        const picked = c.chosenOptionId === o.id
                        const body = (
                          <>
                            <KindBadge option={o} storylines={plan.storylines} />
                            <span className="tmap-opt-title">{o.title}</span>
                            <SwitchTag option={o} timelines={timelines} />
                          </>
                        )
                        const style = { '--c': optionColor(o, plan.storylines) } as CSSProperties
                        return canChoose && !c.chosenOptionId ? (
                          <button key={o.id} className="tmap-opt" style={style} title={o.detail} disabled={busy != null} onClick={() => onChoose(c, o.id)}>
                            {body}
                          </button>
                        ) : (
                          <div key={o.id} className={`tmap-opt${picked ? ' picked' : ''}`} style={style} title={o.detail}>
                            {body}
                            {picked && <span className="lane-go">✓</span>}
                          </div>
                        )
                      })}
                    </div>
                  </article>
                )
              })}
            </section>
          )
        })}
      </div>
    </div>
  )
}
