import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useSleep } from '../lib/sleep'
import { usePatience } from '../lib/patience'
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
  const { refresh: refreshPatience } = usePatience()
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

      <MealsSection settings={settings} patch={patch} />

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
        <label className="check">
          <input
            type="checkbox"
            checked={settings.assumeMissed !== false}
            onChange={(e) => patch({ assumeMissed: e.target.checked })}
          />
          If a chapter's time passes without a choice, assume I missed it
        </label>
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
              refreshPatience() // hours short of the goal cost patience
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
        <h2>⏳ Patience</h2>
        <p className="muted">
          Each hour of sleep gives you 5 patience, and each hour short of your sleep goal costs 10. While your balance is below zero, the debt
          grows by this much every hour (compounding) until you pay it back.
        </p>
        <label>
          Interest on debt
          <select
            value={settings.patienceInterestPerHour}
            onChange={async (e) => {
              await patch({ patienceInterestPerHour: Number(e.target.value) })
              refreshPatience()
            }}
          >
            {[0, 0.5, 1, 2, 3, 5, 10].map((r) => (
              <option key={r} value={r}>
                {r === 0 ? 'No interest' : `${r}% an hour`}
              </option>
            ))}
          </select>
        </label>
        <p className="muted small">Set each tag's default patience from the Board (⏳ Patience by tag).</p>
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
  const [adding, setAdding] = useState(false)
  const [calendarId, setCalendarId] = useState('')
  const [code, setCode] = useState<string | null>(null)
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    api
      .calendarInfo()
      .then((i) => {
        setInfo(i)
        if (i.pending) {
          setAdding(true)
          setCalendarId(i.pending.calendarId)
          setCode(i.pending.code)
        }
      })
      .catch((e) => setMsg({ kind: 'error', text: e.message }))
  }, [setMsg])

  const calendars = info?.calendars ?? []
  const showForm = adding || calendars.length === 0
  const full = calendars.length >= (info?.maxCalendars ?? 10)

  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(text)
    setTimeout(() => setCopied(null), 1500)
  }

  const run = async (key: string, fn: () => Promise<CalendarInfo>) => {
    setBusy(key)
    try {
      setInfo(await fn())
      await onChange()
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
    } finally {
      setBusy(null)
    }
  }

  const link = async () => {
    setBusy('link')
    setHint('')
    try {
      const r = await api.linkCalendar(calendarId)
      if (r.status === 'linked') {
        setCode(null)
        setCalendarId('')
        setAdding(false)
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
      setBusy(null)
    }
  }

  const sa = info?.serviceAccountEmail ?? ''

  return (
    <section className="panel">
      <h2>📅 Google Calendars</h2>
      <p className="muted">
        Link as many calendars as you like (work, school, family…). CYOA plans around events from the ones marked{' '}
        <b>Use for planning</b>. Calendars can be <b>view-only</b>: CYOA just needs <b>one editable</b> calendar (your{' '}
        <b>default</b>) to put the paths you choose on.
      </p>

      {calendars.length > 0 && !info?.hasWritable && (
        <div className="banner warn-banner">
          None of your calendars can be edited by CYOA, so chosen paths won't be added anywhere. Turn on{' '}
          <b>Let CYOA add events</b> for one, or link a calendar shared with <b>Make changes to events</b>.
        </div>
      )}

      {calendars.length > 0 && (
        <ul className="cal-list">
          {calendars.map((c) => (
            <li key={c.key} className="cal-item">
              <span className="dot" style={{ background: c.color ?? 'var(--accent)' }} />
              <div className="cal-name">
                <b>{c.calendarName}</b>
                <div className="muted small">{c.calendarId}</div>
                {(c.isDefault || !c.canWrite || c.readOnly) && (
                  <div className="cal-tags">
                    {c.isDefault && <span className="tag">Default · new events go here</span>}
                    {!c.canWrite && <span className="tag subtle">View-only share</span>}
                    {c.canWrite && c.readOnly && <span className="tag subtle">Never edit</span>}
                  </div>
                )}
              </div>
              <div className="cal-controls">
                <label className="check small">
                  <input
                    type="checkbox"
                    checked={c.readEnabled}
                    disabled={busy !== null}
                    onChange={(e) => run(c.key, () => api.updateCalendar(c.key, { readEnabled: e.target.checked }))}
                  />
                  Use for planning
                </label>
                <label
                  className="check small"
                  title={
                    c.canWrite
                      ? 'Turn off to make sure CYOA never adds or removes events on this calendar'
                      : "Shared as view-only. Change the share to 'Make changes to events' in Google Calendar and re-link it to allow this."
                  }
                >
                  <input
                    type="checkbox"
                    checked={c.writable}
                    disabled={busy !== null || !c.canWrite}
                    onChange={(e) => run(c.key, () => api.updateCalendar(c.key, { readOnly: !e.target.checked }))}
                  />
                  Let CYOA add events
                </label>
                {!c.isDefault && c.writable && (
                  <button
                    className="btn ghost small"
                    disabled={busy !== null}
                    onClick={() => run(c.key, () => api.updateCalendar(c.key, { isDefault: true }))}
                  >
                    Make default
                  </button>
                )}
                <button
                  className="btn ghost danger small"
                  disabled={busy !== null}
                  onClick={() => {
                    if (confirm(`Unlink “${c.calendarName}”? CYOA will stop reading and writing it.`))
                      run(c.key, () => api.removeCalendar(c.key))
                  }}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!showForm && (
        <button className="btn ghost small" onClick={() => setAdding(true)} disabled={full}>
          {full ? `Limit of ${info?.maxCalendars} calendars reached` : '+ Add another calendar'}
        </button>
      )}

      {showForm && (
        <div className="add-cal">
          <ol className="steps">
            <li>
              Open{' '}
              <a href="https://calendar.google.com/calendar/r/settings" target="_blank" rel="noreferrer">
                Google Calendar settings
              </a>{' '}
              and click the calendar under <b>Settings for my calendars</b>.
            </li>
            <li>
              In <b>Share with specific people or groups</b>, add this address. Pick <b>Make changes to events</b>{' '}
              if CYOA may add your chosen paths there, or <b>See all event details</b> to keep it view-only (view-only
              calendars like subscribed/imported ones usually link without a verification code):
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
              placeholder={calendars.length ? 'abc123@group.calendar.google.com' : settings?.email || 'you@gmail.com'}
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
                <b>One more step - prove this calendar is yours.</b> This is needed for calendars CYOA can edit, and
                for calendars whose ID is an email address. On the same Google Calendar settings page, paste this code
                anywhere in the calendar's <b>Description</b>, save, then click <b>Verify</b>. You can remove it
                afterwards. (If you only want CYOA to read this calendar, change the share to{' '}
                <b>See all event details</b> and click <b>Verify</b> again - no code needed for most calendars.)
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
          <div className="row-actions">
            <button className="btn primary" onClick={link} disabled={busy !== null || !calendarId.trim()}>
              {busy === 'link' ? 'Checking…' : code ? 'Verify' : 'Link calendar'}
            </button>
            {calendars.length > 0 && (
              <button
                className="btn ghost"
                onClick={() => {
                  setAdding(false)
                  setCalendarId('')
                  setCode(null)
                  setHint('')
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

function MealsSection({
  settings,
  patch,
}: {
  settings: UserSettings
  patch: (p: Partial<UserSettings>) => Promise<void>
}) {
  const [notes, setNotes] = useState(settings.mealNotes)
  const meals = [
    { label: 'Breakfast', enabled: 'breakfastEnabled', time: 'breakfastTime' },
    { label: 'Lunch', enabled: 'lunchEnabled', time: 'lunchTime' },
    { label: 'Dinner', enabled: 'dinnerEnabled', time: 'dinnerTime' },
  ] as const

  return (
    <section className="panel">
      <h2>🍽 Meals</h2>
      <p className="muted">
        Every planned day includes the meals you eat, each with a few ways to do it (cook, grab something quick, eat
        out…) so you still choose. Breakfast follows your wake-up time when sleep is tracked.
      </p>
      <div className="meal-rows">
        {meals.map((m) => (
          <div key={m.label} className="meal-row">
            <label className="check">
              <input
                type="checkbox"
                checked={settings[m.enabled]}
                onChange={(e) => patch({ [m.enabled]: e.target.checked } as Partial<UserSettings>)}
              />
              I usually eat {m.label.toLowerCase()}
            </label>
            <label className="meal-time">
              around
              <input
                type="time"
                value={settings[m.time]}
                disabled={!settings[m.enabled]}
                onChange={(e) => e.target.value && patch({ [m.time]: e.target.value } as Partial<UserSettings>)}
              />
            </label>
          </div>
        ))}
      </div>
      <label>
        Food notes for the planner
        <textarea
          rows={2}
          maxLength={300}
          placeholder="e.g. vegetarian, cook dinner at home most nights, quick lunches on weekdays"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => notes !== settings.mealNotes && patch({ mealNotes: notes })}
        />
      </label>
    </section>
  )
}
