import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'
import type { PatienceSummary, TagPatience } from '../types'

interface PatienceState {
  patience: PatienceSummary | null
  /** Use a summary a patience call returned. */
  set: (s: PatienceSummary) => void
  refresh: () => Promise<void>
}

const PatienceContext = createContext<PatienceState | null>(null)

// Interest keeps compounding on debt, so re-read the balance now and then.
const REFRESH_MS = 5 * 60_000

export function PatienceProvider({ children }: { children: ReactNode }) {
  const [patience, setPatience] = useState<PatienceSummary | null>(null)

  const refresh = useCallback(async () => {
    try {
      setPatience(await api.patience())
    } catch (e) {
      console.error('Could not load patience', e)
    }
  }, [])

  useEffect(() => {
    // Checking the app costs a point. The server only charges once per 15 minutes,
    // so refreshes and quick tab switches count as the same visit.
    const open = () =>
      api
        .patienceOpen()
        .then(setPatience)
        .catch((e) => console.error('Could not record the visit', e))
    open()
    const onVisible = () => document.visibilityState === 'visible' && open()
    document.addEventListener('visibilitychange', onVisible)
    const t = setInterval(refresh, REFRESH_MS)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  return <PatienceContext.Provider value={{ patience, set: setPatience, refresh }}>{children}</PatienceContext.Provider>
}

export function usePatience(): PatienceState {
  const ctx = useContext(PatienceContext)
  if (!ctx) throw new Error('usePatience must be used inside PatienceProvider')
  return ctx
}

/** Same curve as the backend (app/patience.py): climb to the climax, then fall past it. */
export function parabola(p: TagPatience, minutes: number | null | undefined): number {
  if (p.mode !== 'parabola') return p.points
  const m = minutes == null ? p.idealMinutes : Math.max(0, minutes)
  const v = m <= p.idealMinutes ? p.points * (1 - ((p.idealMinutes - m) / p.idealMinutes) ** 2) : p.points * (1 - ((m - p.idealMinutes) / p.widthMinutes) ** 2)
  return Math.round(Math.max(v, -3 * Math.abs(p.points)) * 10) / 10
}

/** "Peaks at +2 after 30 min, back to 0 by 90 min, then costs you." */
export function curveText(p: TagPatience): string {
  return `Peaks at ${fmtPoints(p.points)} after ${p.idealMinutes} min, back to 0 by ${p.idealMinutes + p.widthMinutes} min, then costs you.`
}

/** "+2", "-3.5", "0" */
export function fmtPoints(n: number): string {
  const r = Math.round(n * 10) / 10
  return r > 0 ? `+${r}` : `${r}`
}
