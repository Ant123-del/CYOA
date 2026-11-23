import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'
import { usePatience } from './patience'
import type { SleepSummary } from '../types'

interface SleepState {
  sleep: SleepSummary | null
  busy: boolean
  error: string | null
  clearError: () => void
  refresh: () => Promise<void>
  start: (at?: string) => Promise<boolean>
  cancel: () => Promise<boolean>
  wake: (at?: string) => Promise<boolean>
  log: (start: string, end: string) => Promise<boolean>
  remove: (id: string) => Promise<boolean>
}

const SleepContext = createContext<SleepState | null>(null)

const REFRESH_MS = 5 * 60_000

export function SleepProvider({ children }: { children: ReactNode }) {
  const [sleep, setSleep] = useState<SleepSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { refresh: refreshPatience } = usePatience()

  const refresh = useCallback(async () => {
    try {
      setSleep(await api.sleep())
    } catch (e) {
      console.error('Could not load sleep', e)
    }
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, REFRESH_MS)
    // Phones keep tabs open overnight: re-check when the app comes back to the foreground.
    const onVisible = () => document.visibilityState === 'visible' && refresh()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  const run = (fn: () => Promise<SleepSummary>) => async () => {
    setBusy(true)
    setError(null)
    try {
      setSleep(await fn())
      refreshPatience() // waking up, logging or deleting a sleep moves the balance
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const value: SleepState = {
    sleep,
    busy,
    error,
    clearError: () => setError(null),
    refresh,
    start: (at) => run(() => api.sleepStart(at))(),
    cancel: () => run(() => api.sleepCancel())(),
    wake: (at) => run(() => api.sleepWake(at))(),
    log: (start, end) => run(() => api.sleepLog(start, end))(),
    remove: (id) => run(() => api.sleepDelete(id))(),
  }
  return <SleepContext.Provider value={value}>{children}</SleepContext.Provider>
}

export function useSleep(): SleepState {
  const ctx = useContext(SleepContext)
  if (!ctx) throw new Error('useSleep must be used inside SleepProvider')
  return ctx
}
