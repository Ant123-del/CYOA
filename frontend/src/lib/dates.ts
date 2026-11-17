/** Local YYYY-MM-DD for a Date (not UTC). */
export function isoDate(d: Date = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  return isoDate(new Date(y, m - 1, d + n))
}

export function prettyDate(iso: string, opts: Intl.DateTimeFormatOptions = { weekday: 'long', month: 'short', day: 'numeric' }) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, opts)
}

export function nowHM(): string {
  const n = new Date()
  return `${String(n.getHours()).padStart(2, '0')}:${String(n.getMinutes()).padStart(2, '0')}`
}

export function fmtTime(hm: string): string {
  const [h, m] = hm.split(':').map(Number)
  const d = new Date()
  d.setHours(h, m, 0, 0)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 12)
}

export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/** Clock time of an ISO timestamp, in the device's timezone. */
export function fmtClock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** "7h 20m" from a number of hours. */
export function fmtHours(hours: number): string {
  const total = Math.round(hours * 60)
  const h = Math.floor(total / 60)
  const m = total % 60
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`
}

/** The most recent moment (not in the future) whose local clock reads HH:MM, as ISO. */
export function pastTimeToIso(hm: string, now: Date = new Date()): string {
  const [h, m] = hm.split(':').map(Number)
  const d = new Date(now)
  d.setHours(h, m, 0, 0)
  if (d.getTime() > now.getTime()) d.setDate(d.getDate() - 1)
  return d.toISOString()
}

/** Value for <input type="datetime-local"> from a Date. */
export function toLocalInput(d: Date): string {
  return `${isoDate(d)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
