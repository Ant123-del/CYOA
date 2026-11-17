import { auth } from './firebase'
import type {
  CalendarEvent,
  CalendarInfo,
  Chapter,
  DayPlan,
  DaySummary,
  Goal,
  GoalInput,
  UserSettings,
} from '../types'

const BASE = import.meta.env.VITE_API_URL ?? ''

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const user = auth.currentUser
  if (!user) throw new ApiError(401, 'Not signed in')
  const token = await user.getIdToken()
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data)
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg)
  }
  return (await res.json()) as T
}

export const api = {
  me: () => request<UserSettings>('GET', '/api/me'),
  updateMe: (patch: Partial<UserSettings>) => request<UserSettings>('PATCH', '/api/me', patch),
  testEmail: () => request<{ sentTo: string }>('POST', '/api/notifications/test'),

  goals: () => request<Goal[]>('GET', '/api/goals'),
  createGoal: (g: GoalInput) => request<Goal>('POST', '/api/goals', g),
  updateGoal: (id: string, patch: Partial<GoalInput>) => request<Goal>('PATCH', `/api/goals/${id}`, patch),
  deleteGoal: (id: string) => request<{ ok: boolean }>('DELETE', `/api/goals/${id}`),

  days: (start: string, end: string) => request<DaySummary[]>('GET', `/api/days?start=${start}&end=${end}`),
  day: (date: string) => request<DayPlan | null>('GET', `/api/days/${date}`),
  saveDay: (plan: DayPlan) => request<DayPlan>('PUT', `/api/days/${plan.date}`, plan),
  deleteDay: (date: string) => request<{ ok: boolean }>('DELETE', `/api/days/${date}`),
  importCalendar: (date: string) => request<Chapter[]>('POST', `/api/days/${date}/import-calendar`),
  choose: (date: string, chapterId: string, optionId: string, addToCalendar = true) =>
    request<{ plan: DayPlan; calendar: string }>('POST', `/api/days/${date}/chapters/${chapterId}/choose`, {
      optionId,
      addToCalendar,
    }),
  resetChoice: (date: string, chapterId: string) =>
    request<DayPlan>('POST', `/api/days/${date}/chapters/${chapterId}/reset`),

  planDay: (body: {
    date: string
    priorities: string
    dayStart: string
    dayEnd: string
    useCalendar: boolean
    routes: number
    goalIds?: string[] | null
  }) => request<DayPlan>('POST', '/api/ai/plan-day', body),
  chapterOptions: (date: string, chapterId: string, hint: string) =>
    request<DayPlan>('POST', '/api/ai/chapter-options', { date, chapterId, hint }),

  googleAuthUrl: () => request<{ url: string }>('GET', '/api/google/auth-url'),
  googleDisconnect: () => request<{ ok: boolean }>('POST', '/api/google/disconnect'),
  calendars: () => request<CalendarInfo[]>('GET', '/api/google/calendars'),
  events: (date: string) => request<CalendarEvent[]>('GET', `/api/google/events?date=${date}`),
}
