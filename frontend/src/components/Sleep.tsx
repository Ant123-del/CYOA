import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useSleep } from '../lib/sleep'
import { fmtClock, fmtHours, fmtTime, isoDate, pastTimeToIso, prettyDate, toLocalInput } from '../lib/dates'
import type { SleepStatus } from '../types'

export const SLEEP_LABEL: Record<SleepStatus, string> = {
  unknown: 'Not tracked yet',
  rested: 'Well rested',
  low: 'Running low',
  deprived: 'Sleep deprived',
}

const SLEEP_ADVICE: Record<SleepStatus, string> = {
  unknown: 'Tap 🌙 Going to sleep tonight and ☀️ Woke up in the morning. The planner will start pacing your days around it.',
  rested: "Nicely rested. Your plans will run at full speed.",
  low: "A little short. The planner will put the hard stuff early and keep tonight's bedtime protected.",
  deprived: "You're running on fumes. New plans will go easier, with lighter routes and a rest break.",
}

function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

/** Top-bar button + the full-screen "you're asleep" view. */
export function SleepControl() {
  const { sleep, busy, start } = useSleep()
  const [open, setOpen] = useState(true)
  const [morning, setMorning] = useState(false)

  if (!sleep) return null

  const onClick = async () => {
    if (sleep.asleep) return setOpen(true)
    if (await start()) setOpen(true)
  }

  return (
    <>
      <button
        className={`btn small sleep-btn${sleep.asleep ? ' asleep' : ''}`}
        onClick={onClick}
        disabled={busy}
        title={sleep.asleep ? 'Mark yourself awake' : 'Start tracking sleep'}
      >
        <span aria-hidden>{sleep.asleep ? '☀️' : '🌙'}</span>
        <span className="sleep-btn-label">{sleep.asleep ? 'Woke up' : 'Going to sleep'}</span>
      </button>
      {((sleep.asleep && open) || morning) &&
        createPortal(
          morning ? (
            <MorningView onDone={() => setMorning(false)} />
          ) : (
            <AsleepView onMinimize={() => setOpen(false)} onWoke={() => setMorning(true)} />
          ),
          document.body,
        )}
    </>
  )
}

function AsleepView({ onMinimize, onWoke }: { onMinimize: () => void; onWoke: () => void }) {
  const { sleep, busy, error, clearError, wake, cancel } = useSleep()
  const now = useNow()
  const [showTime, setShowTime] = useState(false)
  const [wokeAt, setWokeAt] = useState('')
  const since = sleep?.sleepingSince

  useEffect(() => clearError, [clearError])

  if (!sleep || !since) return null
  const elapsed = (now - new Date(since).getTime()) / 3_600_000

  const doWake = async (at?: string) => {
    if (await wake(at)) onWoke()
  }

  return (
    <div className="sleep-overlay" role="dialog" aria-modal="true" aria-label="Sleeping">
      <div className="sleep-sky" aria-hidden>
        <span>✦</span>
        <span>✧</span>
        <span>✦</span>
        <span>✧</span>
      </div>
      <div className="sleep-panel">
        <div className="sleep-moon" aria-hidden>
          🌙
        </div>
        <p className="sleep-kicker">Sleeping since {fmtClock(since)}</p>
        <div className="sleep-elapsed">{fmtHours(Math.max(0, elapsed))}</div>
        <p className="sleep-sub">Rest well, adventurer. Tap below when you're up.</p>

        {error && (
          <div className="banner error" onClick={clearError}>
            {error}
          </div>
        )}

        <button className="btn primary big wake-btn" onClick={() => doWake()} disabled={busy}>
          ☀️ I woke up
        </button>

        {showTime ? (
          <form
            className="wake-time"
            onSubmit={(e) => {
              e.preventDefault()
              if (wokeAt) doWake(pastTimeToIso(wokeAt))
            }}
          >
            <label>
              I actually woke up at
              <input type="time" value={wokeAt} onChange={(e) => setWokeAt(e.target.value)} autoFocus required />
            </label>
            <button className="btn ghost" type="submit" disabled={busy || !wokeAt}>
              Save
            </button>
          </form>
        ) : (
          <button className="link-btn" onClick={() => setShowTime(true)}>
            Woke up earlier? Set the time
          </button>
        )}

        <div className="sleep-foot">
          <button className="link-btn" onClick={() => cancel()} disabled={busy}>
            Cancel, I'm not sleeping
          </button>
          <button className="link-btn" onClick={onMinimize}>
            Keep using the app
          </button>
        </div>
      </div>
    </div>
  )
}

function MorningView({ onDone }: { onDone: () => void }) {
  const { sleep } = useSleep()
  const navigate = useNavigate()
  const last = sleep?.sessions[0]
  const hours = last?.end ? (new Date(last.end).getTime() - new Date(last.start).getTime()) / 3_600_000 : null

  const go = () => {
    onDone()
    navigate('/today')
  }

  return (
    <div className="sleep-overlay morning" role="dialog" aria-modal="true" aria-label="Good morning">
      <div className="sleep-panel">
        <div className="sleep-moon" aria-hidden>
          ☀️
        </div>
        <p className="sleep-kicker">Good morning</p>
        {hours !== null && <div className="sleep-elapsed">{fmtHours(hours)}</div>}
        {hours !== null && <p className="sleep-sub">of sleep{last ? `, ${fmtClock(last.start)} to ${fmtClock(last.end!)}` : ''}</p>}
        {sleep && (
          <>
            <span className={`sleep-status status-${sleep.status}`}>{SLEEP_LABEL[sleep.status]}</span>
            <p className="sleep-sub">{SLEEP_ADVICE[sleep.status]}</p>
            <p className="sleep-sub">
              Tonight, aim for lights out by <b>{fmtTime(sleep.suggestedBedtime)}</b>.
            </p>
          </>
        )}
        <button className="btn primary big" onClick={go}>
          Start today's adventure →
        </button>
      </div>
    </div>
  )
}

function minutesOf(hm: string) {
  const [h, m] = hm.split(':').map(Number)
  return h * 60 + m
}

/** Signed minutes from b to a on a 24h clock, in (-720, 720]. */
function clockDiff(a: string, b: string) {
  const d = (((minutesOf(a) - minutesOf(b)) % 1440) + 1440) % 1440
  return d > 720 ? d - 1440 : d
}

/** Sleep status + tonight's suggested bedtime, for the Today page. */
export function SleepCard() {
  const { sleep, busy, error, clearError, log, remove } = useSleep()
  const [logOpen, setLogOpen] = useState(false)
  const [logStart, setLogStart] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    d.setHours(23, 0, 0, 0)
    return toLocalInput(d)
  })
  const [logEnd, setLogEnd] = useState(() => `${isoDate()}T07:00`)

  if (!sleep) return null
  const drift = sleep.typicalBedtime ? clockDiff(sleep.typicalBedtime, sleep.suggestedBedtime) : 0

  return (
    <section className={`sleep-card status-${sleep.status}`}>
      <div className="sleep-card-head">
        <h2>💤 Sleep</h2>
        <span className={`sleep-status status-${sleep.status}`}>{SLEEP_LABEL[sleep.status]}</span>
      </div>

      {sleep.status !== 'unknown' && (
        <div className="sleep-stats">
          {sleep.lastSleepHours !== null && <Stat label="Last sleep" value={fmtHours(sleep.lastSleepHours)} />}
          {sleep.hoursAwake !== null && <Stat label="Awake for" value={fmtHours(sleep.hoursAwake)} />}
          <Stat label={`Debt (${sleep.nightsTracked} night${sleep.nightsTracked === 1 ? '' : 's'})`} value={fmtHours(sleep.debtHours)} />
          {sleep.avgHours7d !== null && <Stat label="Average" value={`${fmtHours(sleep.avgHours7d)} / ${sleep.targetHours}h`} />}
        </div>
      )}

      <p className="sleep-advice">{SLEEP_ADVICE[sleep.status]}</p>

      <div className="sleep-tonight">
        <span aria-hidden>🌙</span>
        <div>
          <b>
            Tonight: wind down at {fmtTime(sleep.windDownAt)}, lights out by {fmtTime(sleep.suggestedBedtime)}
          </b>
          <div className="muted small">
            {sleep.targetHours}h before a {fmtTime(sleep.wakeAnchor)} wake-up
            {sleep.debtHours >= 1 ? ', plus a little extra to pay down your debt' : ''}.
            {drift > 45 &&
              ` You usually turn in around ${fmtTime(sleep.typicalBedtime!)}; moving 15 to 30 minutes earlier each night is easier than one big jump.`}
          </div>
        </div>
      </div>

      <details className="sleep-more" open={logOpen} onToggle={(e) => setLogOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Forgot to track? Sleep history</summary>
        {error && (
          <div className="banner error" onClick={clearError}>
            {error}
          </div>
        )}
        <form
          className="sleep-log"
          onSubmit={async (e) => {
            e.preventDefault()
            await log(new Date(logStart).toISOString(), new Date(logEnd).toISOString())
          }}
        >
          <label>
            Fell asleep
            <input type="datetime-local" value={logStart} onChange={(e) => setLogStart(e.target.value)} required />
          </label>
          <label>
            Woke up
            <input type="datetime-local" value={logEnd} onChange={(e) => setLogEnd(e.target.value)} required />
          </label>
          <button className="btn ghost" type="submit" disabled={busy}>
            Add sleep
          </button>
        </form>
        {sleep.sessions.length > 0 && (
          <ul className="sleep-history">
            {sleep.sessions.map((s) => (
              <li key={s.id}>
                <span className="sh-date">{prettyDate(isoDate(new Date(s.end!)), { weekday: 'short', month: 'short', day: 'numeric' })}</span>
                <span className="sh-range">
                  {fmtClock(s.start)} – {fmtClock(s.end!)}
                </span>
                <span className="sh-dur">{fmtHours((new Date(s.end!).getTime() - new Date(s.start).getTime()) / 3_600_000)}</span>
                <button
                  className="icon-btn"
                  title="Delete this entry"
                  onClick={() => confirm('Delete this sleep entry?') && remove(s.id)}
                  disabled={busy}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}
