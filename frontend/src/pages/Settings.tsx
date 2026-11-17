import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { browserTimezone } from '../lib/dates'
import type { CalendarInfo, UserSettings } from '../types'

const TIMEZONES: string[] = (() => {
  try {
    return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone')
  } catch {
    return [browserTimezone(), 'UTC']
  }
})()

export default function Settings() {
  const { settings, setSettings, refreshSettings } = useAuth()
  const [params, setParams] = useSearchParams()
  const [calendars, setCalendars] = useState<CalendarInfo[]>([])
  const [msg, setMsg] = useState<{ kind: 'info' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const status = params.get('calendar')
    if (status === 'connected') {
      setMsg({ kind: 'info', text: 'Google Calendar connected 🎉' })
      refreshSettings()
      setParams({})
    } else if (status === 'error') {
      setMsg({ kind: 'error', text: `Calendar connection failed (${params.get('reason') ?? 'unknown'}).` })
      setParams({})
    }
    
  }, [])

  useEffect(() => {
    if (settings?.googleConnected) api.calendars().then(setCalendars).catch(() => setCalendars([]))
  }, [settings?.googleConnected])

  if (!settings) return <p className="muted page">Loading settings… (is the backend running on :8000?)</p>

  const patch = async (p: Partial<UserSettings>) => {
    setSettings({ ...settings, ...p })
    try {
      setSettings(await api.updateMe(p))
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
    }
  }

  const connect = async () => {
    setBusy(true)
    try {
      const { url } = await api.googleAuthUrl()
      window.location.href = url
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
      setBusy(false)
    }
  }

  const disconnect = async () => {
    await api.googleDisconnect()
    await refreshSettings()
    setCalendars([])
  }

  const testEmail = async () => {
    try {
      const r = await api.testEmail()
      setMsg({ kind: 'info', text: `Test email sent to ${r.sentTo} (or logged in the backend console if SMTP isn't set up).` })
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

      <section className="panel">
        <h2>📅 Google Calendar</h2>
        <p className="muted">
          CYOA reads your schedule to build yes / yes-and / no / no-and chapters, and adds the path you pick to your
          calendar.
        </p>
        {settings.googleConnected ? (
          <>
            <label>
              Calendar to use
              <select value={settings.calendarId} onChange={(e) => patch({ calendarId: e.target.value })}>
                <option value="primary">Primary calendar</option>
                {calendars
                  .filter((c) => !c.primary)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.summary}
                    </option>
                  ))}
              </select>
            </label>
            <button className="btn ghost danger small" onClick={disconnect}>
              Disconnect
            </button>
          </>
        ) : (
          <button className="btn primary" onClick={connect} disabled={busy}>
            {busy ? 'Redirecting…' : 'Connect Google Calendar'}
          </button>
        )}
      </section>

      <section className="panel">
        <h2>✉️ Reminder emails</h2>
        <p className="muted">When a new chapter is about to begin, we email you its paths so you can choose.</p>
        <label className="check">
          <input type="checkbox" checked={settings.emailReminders} onChange={(e) => patch({ emailReminders: e.target.checked })} />
          Email me when it's time to choose
        </label>
        <div className="row">
          <label>
            Send to
            <input
              type="email"
              value={settings.notifyEmail}
              onChange={(e) => setSettings({ ...settings, notifyEmail: e.target.value })}
              onBlur={(e) => patch({ notifyEmail: e.target.value })}
            />
          </label>
          <label>
            Minutes before chapter
            <input
              type="number"
              min={0}
              max={120}
              value={settings.reminderLeadMinutes}
              onChange={(e) => patch({ reminderLeadMinutes: Number(e.target.value) })}
            />
          </label>
        </div>
        <button className="btn ghost small" onClick={testEmail}>
          Send test email
        </button>
        <p className="muted small">Changes apply to plans when they're next saved.</p>
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
    </div>
  )
}
