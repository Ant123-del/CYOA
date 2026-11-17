import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useSleep } from '../lib/sleep'
import { browserTimezone } from '../lib/dates'
import type { AIMemory, CalendarInfo, UserSettings } from '../types'

const TIMEZONES: string[] = (() => {
  try {
    return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone')
  } catch {
    return [browserTimezone(), 'UTC']
  }
})()

export default function Settings() {
  const { settings, setSettings, refreshSettings, logOut } = useAuth()
  const { refresh: refreshSleep } = useSleep()
  const [msg, setMsg] = useState<{ kind: 'info' | 'error'; text: string } | null>(null)

  if (!settings) return <p className="muted page">Loading settings…</p>

  const patch = async (p: Partial<UserSettings>) => {
    setSettings({ ...settings, ...p })
    try {
      setSettings(await api.updateMe(p))
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
    }
  }

  const testEmail = async () => {
    try {
      const r = await api.testEmail()
      setMsg({ kind: 'info', text: `Test email sent to ${r.sentTo}.` })
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
    }
  }

  return (
    <div className="page narrow">
      <div className="page-head">
        <h1>Settings</h1>
      </div>
      {msg && (
        <div className={`banner ${msg.kind}`} onClick={() => setMsg(null)}>
          {msg.text}
        </div>
      )}

      <MemorySection setMsg={setMsg} />

      <CalendarSection onChange={refreshSettings} setMsg={setMsg} />

      <section className="panel">
        <h2>✉️ Reminder emails</h2>
        <p className="muted">When a new chapter is about to begin, we email you its paths so you can choose.</p>
        <label className="check">
          <input type="checkbox" checked={settings.emailReminders} onChange={(e) => patch({ emailReminders: e.target.checked })} />
          Email me at <b>{settings.email}</b> when it's time to choose
        </label>
        <label>
          Minutes before each chapter
          <input
            type="number"
            min={0}
            max={240}
            value={settings.reminderLeadMinutes}
            onChange={(e) => patch({ reminderLeadMinutes: Math.min(240, Math.max(0, Number(e.target.value))) })}
          />
        </label>
        <button className="btn ghost small" onClick={testEmail}>
          Send test email
        </button>
        <p className="muted small">Changes apply to plans when they're next saved.</p>
      </section>

      <section className="panel">
        <h2>💤 Sleep</h2>
        <p className="muted">
          How much sleep you're aiming for. CYOA uses it to spot sleep debt, suggest a bedtime, and pace the days it plans.
        </p>
        <label>
          Sleep goal per night
          <select
            value={settings.sleepTargetHours}
            onChange={async (e) => {
              await patch({ sleepTargetHours: Number(e.target.value) })
              refreshSleep()
            }}
          >
            {[6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10].map((h) => (
              <option key={h} value={h}>
                {h} hours
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="panel">
        <h2>🌍 Timezone</h2>
        <select value={settings.timezone} onChange={(e) => patch({ timezone: e.target.value })}>
          {(TIMEZONES.includes(settings.timezone) ? TIMEZONES : [settings.timezone, ...TIMEZONES]).map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
        {settings.timezone !== browserTimezone() && (
          <button className="btn ghost small" onClick={() => patch({ timezone: browserTimezone() })}>
            Use this device's timezone ({browserTimezone()})
          </button>
        )}
      </section>

      <section className="panel account">
        <h2>👤 Account</h2>
        <p className="muted">Signed in as {settings.email}</p>
        <button className="btn ghost" onClick={logOut}>
          Sign out
        </button>
      </section>
    </div>
  )
}

function MemorySection({ setMsg }: { setMsg: (m: { kind: 'info' | 'error'; text: string } | null) => void }) {
  const [mem, setMem] = useState<AIMemory | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .memory()
      .then(setMem)
      .catch((e) => setMsg({ kind: 'error', text: e.message }))
  }, [setMsg])

  const run = async (fn: () => Promise<AIMemory>) => {
    setBusy(true)
    try {
      setMem(await fn())
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const add = async () => {
    const t = text.trim()
    if (!t) return
    await run(() => api.addMemoryNote(t))
    setText('')
  }

  const clearAll = () => {
    if (confirm('Forget everything the AI has learned about you? Your past plans stay, but notes and request history are erased.'))
      run(api.clearMemory)
  }

  const notes = [...(mem?.notes ?? [])].reverse()

  return (
    <section className="panel">
      <h2>🧠 What the AI knows about you</h2>
      <p className="muted">
        The planner remembers your requests and the paths you actually take, and learns your patterns over time. Tell
        it anything that should shape your days.
      </p>
      <div className="copy-row">
        <input
          placeholder="e.g. I focus best before lunch; gym on Mon/Wed/Fri"
          value={text}
          maxLength={280}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
        />
        <button className="btn primary small" onClick={add} disabled={busy || !text.trim()}>
          Remember
        </button>
      </div>
      {mem === null ? (
        <p className="muted small">Loading…</p>
      ) : notes.length === 0 ? (
        <p className="muted small">Nothing yet. Plan a few days and it'll start picking up on how you work.</p>
      ) : (
        <ul className="memory-notes">
          {notes.map((n) => (
            <li key={n.id}>
              <span className="memory-source" title={n.source === 'user' ? 'You told it this' : 'It learned this'}>
                {n.source === 'user' ? '🗣️' : '✨'}
              </span>
              <span className="memory-text">{n.text}</span>
              <button className="btn ghost small" onClick={() => run(() => api.deleteMemoryNote(n.id))} disabled={busy}>
                Forget
              </button>
            </li>
          ))}
        </ul>
      )}
      {mem && (mem.notes.length > 0 || mem.log.length > 0) && (
        <button className="btn ghost danger small" onClick={clearAll} disabled={busy}>
          Forget everything
        </button>
      )}
    </section>
  )
}

function CalendarSection({
  onChange,
  setMsg,
}: {
  onChange: () => Promise<void>
  setMsg: (m: { kind: 'info' | 'error'; text: string } | null) => void
}) {
  const { settings } = useAuth()
  const [info, setInfo] = useState<CalendarInfo | null>(null)
  const [calendarId, setCalendarId] = useState('')
  const [code, setCode] = useState<string | null>(null)
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    api
      .calendarInfo()
      .then((i) => {
        setInfo(i)
        if (i.pending) {
          setCalendarId(i.pending.calendarId)
          setCode(i.pending.code)
        }
      })
      .catch((e) => setMsg({ kind: 'error', text: e.message }))
  }, [setMsg])

  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(text)
    setTimeout(() => setCopied(null), 1500)
  }

  const link = async () => {
    setBusy(true)
    setHint('')
    try {
      const r = await api.linkCalendar(calendarId)
      if (r.status === 'linked') {
        setCode(null)
        setMsg({ kind: 'info', text: `Linked “${r.calendarName}” 🎉` })
        setInfo(await api.calendarInfo())
        await onChange()
      } else {
        setCalendarId(r.calendarId)
        setCode(r.code ?? null)
        setHint(r.message ?? '')
      }
    } catch (e) {
      setHint((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const unlink = async () => {
    await api.unlinkCalendar()
    setInfo(await api.calendarInfo())
    setCalendarId('')
    setCode(null)
    await onChange()
  }

  const sa = info?.serviceAccountEmail ?? ''

  return (
    <section className="panel">
      <h2>📅 Google Calendar</h2>
      <p className="muted">
        CYOA reads your schedule to build yes / yes-and / no / no-and chapters, and adds the path you pick to your
        calendar.
      </p>

      {info?.linked ? (
        <>
          <div className="linked-cal">
            <span className="dot" style={{ background: 'var(--yes)' }} />
            <div>
              <b>{info.calendarName}</b>
              <div className="muted small">{info.calendarId}</div>
            </div>
          </div>
          <button className="btn ghost danger small" onClick={unlink}>
            Unlink
          </button>
        </>
      ) : (
        <>
          <ol className="steps">
            <li>
              Open{' '}
              <a href="https://calendar.google.com/calendar/r/settings" target="_blank" rel="noreferrer">
                Google Calendar settings
              </a>{' '}
              and click your calendar under <b>Settings for my calendars</b>.
            </li>
            <li>
              In <b>Share with specific people or groups</b>, add this address with <b>Make changes to events</b>:
              <div className="copy-row">
                <code>{sa || '…'}</code>
                <button className="btn ghost small" onClick={() => copy(sa)} disabled={!sa}>
                  {copied === sa ? 'Copied ✓' : 'Copy'}
                </button>
              </div>
            </li>
            <li>
              Scroll to <b>Integrate calendar</b> and copy the <b>Calendar ID</b>. (For your main calendar it's your
              Gmail address.)
            </li>
          </ol>
          <label>
            Calendar ID
            <input
              placeholder={settings?.email || 'you@gmail.com'}
              value={calendarId}
              onChange={(e) => {
                setCalendarId(e.target.value)
                setCode(null)
              }}
            />
          </label>

          {code && (
            <div className="verify">
              <p>
                <b>One more step - prove this calendar is yours.</b> On the same Google Calendar settings page, paste
                this code anywhere in the calendar's <b>Description</b>, save, then click <b>Verify</b>. You can remove
                it afterwards.
              </p>
              <div className="copy-row">
                <code>{code}</code>
                <button className="btn ghost small" onClick={() => copy(code)}>
                  {copied === code ? 'Copied ✓' : 'Copy'}
                </button>
              </div>
            </div>
          )}
          {hint && <p className="error small">{hint}</p>}
          <button className="btn primary" onClick={link} disabled={busy || !calendarId.trim()}>
            {busy ? 'Checking…' : code ? 'Verify' : 'Link calendar'}
          </button>
        </>
      )}
    </section>
  )
}
