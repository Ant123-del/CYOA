import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { prettyDate } from '../lib/dates'
import type { PlanJob } from '../types'

const STEPS = [
  'Reading your calendars…',
  'Weighing your priorities…',
  'Sketching your storylines…',
  'Finding time for breakfast, lunch and dinner…',
  'Building in breaks so you don’t burn out…',
  'Writing backup routes for every chapter…',
  'Turning meetings into yes / yes-and / no / no-and…',
  'Checking nothing overlaps…',
  'Adding the finishing touches…',
]

export default function PlanningScreen({
  job,
  email,
  onEmail,
}: {
  job: PlanJob
  email: string
  onEmail: () => Promise<void>
}) {
  const [started] = useState(() => (job.createdAt ? new Date(job.createdAt).getTime() : Date.now()))
  const [now, setNow] = useState(() => Date.now())
  const [sending, setSending] = useState(false)

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  const elapsed = Math.max(0, Math.round((now - started) / 1000))
  const step = STEPS[Math.floor(elapsed / 5) % STEPS.length]

  const requestEmail = async () => {
    setSending(true)
    try {
      await onEmail()
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="panel planning-screen" aria-live="polite">
      <div className="compass spin big-compass" aria-hidden>
        🧭
      </div>
      <h2>Writing your adventure for {prettyDate(job.date)}</h2>
      <p className="planning-step" key={step}>
        {step}
      </p>
      <div className="indeterminate" aria-hidden>
        <div />
      </div>
      <p className="muted small">
        {elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`} · usually takes about a minute
      </p>

      <div className="planning-leave">
        {job.notifyEmail ? (
          <p>
            ✉️ We’ll email <b>{email}</b> as soon as it’s ready. You can close this page.
          </p>
        ) : (
          <>
            <button className="btn primary" onClick={requestEmail} disabled={sending}>
              {sending ? 'One sec…' : '✉️ Email me when it’s ready'}
            </button>
            <p className="muted small">
              No need to wait here - if you leave this page, we’ll email you at {email} when your day is ready.
            </p>
          </>
        )}
        <div className="planning-links">
          <Link className="btn ghost small" to="/board">
            Go to Board
          </Link>
          <Link className="btn ghost small" to="/today">
            Go to Today
          </Link>
        </div>
      </div>
    </section>
  )
}
