import { auth } from './firebase'
import type {
  AIMemory,
  CalendarEvent,
  CalendarInfo,
  CalendarLinkResult,
  Chapter,
  DayPlan,
  DaySummary,
  Goal,
  GoalInput,
  Manifestation,
  ManifestationInput,
  PlanJob,
  SleepSummary,
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
  setMissed: (date: string, chapterId: string, missed: boolean) =>
    request<DayPlan>('POST', `/api/days/${date}/chapters/${chapterId}/missed`, { missed }),
  revise: (date: string, feedback: string, timelineId: string | null, rewrite = false) =>
    request<{ plan: DayPlan; reply: string; applied: number }>('POST', '/api/ai/revise', { date, feedback, timelineId, rewrite }),
  resetChoice: (date: string, chapterId: string) =>
    request<DayPlan>('POST', `/api/days/${date}/chapters/${chapterId}/reset`),

  planDay: (body: {
    date: string
    priorities: string
    dayStart: string
    dayEnd: string
    useCalendar: boolean
    routes: number
    timelines: number
    goalIds?: string[] | null
  }) => request<PlanJob>('POST', '/api/ai/plan-day', body),
  activePlanJob: (date: string) => request<PlanJob | null>('GET', `/api/ai/plan-jobs?date=${date}`),
  planJob: (jobId: string) => request<PlanJob>('GET', `/api/ai/plan-jobs/${jobId}`),
  runPlanJob: (jobId: string) => request<PlanJob>('POST', `/api/ai/plan-jobs/${jobId}/run`),
  emailWhenReady: (jobId: string) => request<PlanJob>('POST', `/api/ai/plan-jobs/${jobId}/email`),
  chapterOptions: (date: string, chapterId: string, hint: string) =>
    request<DayPlan>('POST', '/api/ai/chapter-options', { date, chapterId, hint }),
  memory: () => request<AIMemory>('GET', '/api/ai/memory'),
  addMemoryNote: (text: string) => request<AIMemory>('POST', '/api/ai/memory/notes', { text }),
  deleteMemoryNote: (id: string) => request<AIMemory>('DELETE', `/api/ai/memory/notes/${id}`),
  clearMemory: () => request<AIMemory>('DELETE', '/api/ai/memory'),

  calendarInfo: () => request<CalendarInfo>('GET', '/api/calendar'),
  linkCalendar: (calendarId: string) => request<CalendarLinkResult>('POST', '/api/calendar/link', { calendarId }),
  unlinkCalendar: () => request<{ ok: boolean }>('POST', '/api/calendar/unlink'),
  updateCalendar: (key: string, patch: { isDefault?: boolean; readEnabled?: boolean; readOnly?: boolean }) =>
    request<CalendarInfo>('PATCH', `/api/calendar/${key}`, patch),
  removeCalendar: (key: string) => request<CalendarInfo>('DELETE', `/api/calendar/${key}`),
  sleep: () => request<SleepSummary>('GET', '/api/sleep'),
  sleepStart: (at?: string) => request<SleepSummary>('POST', '/api/sleep/start', { at: at ?? null }),
  sleepCancel: () => request<SleepSummary>('POST', '/api/sleep/cancel'),
  sleepWake: (at?: string) => request<SleepSummary>('POST', '/api/sleep/wake', { at: at ?? null }),
  sleepLog: (start: string, end: string) => request<SleepSummary>('POST', '/api/sleep/log', { start, end }),
  sleepDelete: (id: string) => request<SleepSummary>('DELETE', `/api/sleep/${id}`),

  manifestations: () => request<Manifestation[]>('GET', '/api/manifestations'),
  createManifestation: (m: ManifestationInput) => request<Manifestation>('POST', '/api/manifestations', m),
  updateManifestation: (id: string, patch: Partial<Omit<ManifestationInput, 'kind'>>) =>
    request<Manifestation>('PATCH', `/api/manifestations/${id}`, patch),
  deleteManifestation: (id: string) => request<{ ok: boolean }>('DELETE', `/api/manifestations/${id}`),
  suggestCorrected: (title: string, problem: string, naturalManifestations: string[]) =>
    request<{ suggestions: string[] }>('POST', '/api/manifestations/suggest', { title, problem, naturalManifestations }),

  events: (date: string) => request<CalendarEvent[]>('GET', `/api/calendar/events?date=${date}`),
}
