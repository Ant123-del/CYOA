export type GoalStatus = 'backlog' | 'todo' | 'doing' | 'done'
export type Priority = 'high' | 'medium' | 'low'
export type OptionKind = 'yes' | 'yes_and' | 'no' | 'no_and' | 'route'
export type ChapterSource = 'calendar' | 'goal' | 'custom' | 'meal' | 'break'

export interface Goal {
  id: string
  title: string
  description: string
  status: GoalStatus
  priority: Priority
  estimateMinutes: number | null
  dueDate: string | null
  tags: string[]
  order: number
  createdAt?: string | null
  updatedAt?: string | null
}

export type GoalInput = Omit<Goal, 'id' | 'createdAt' | 'updatedAt'>

export interface Option {
  id: string
  kind: OptionKind
  storylineId: string | null
  title: string
  detail: string
  durationMinutes: number | null
  goalIds: string[]
  nextTimelineId?: string | null // where the day goes after this choice (null = stay)
}

export interface Chapter {
  id: string
  start: string
  end: string
  title: string
  priority: Priority
  source: ChapterSource
  calendarEventId: string | null
  calendarId?: string | null
  calendarName?: string | null
  calendarColor?: string | null
  scheduledCalendarId?: string | null
  timelineId?: string | null
  activityId?: string | null
  options: Option[]
  chosenOptionId: string | null
  chosenAt: string | null
  scheduledEventId: string | null
}

export interface Storyline {
  id: string
  name: string
  description: string
  color: string | null
}

export interface Timeline {
  id: string
  name: string
  description: string
  color: string | null
  role?: 'healthy' | 'recovery' | 'rebel' | null
  keptEventIds: string[]
  skippedEvents: string[]
}

export interface DayPlan {
  date: string
  priorities: string
  dayStart: string
  dayEnd: string
  summary: string
  storylines: Storyline[]
  timelines?: Timeline[]
  currentTimelineId?: string | null
  chapters: Chapter[]
  updatedAt?: string | null
}

export interface DaySummary {
  date: string
  chapters: number
  chosen: number
  storylines: number
}

export interface UserSettings {
  email: string
  displayName: string
  timezone: string
  reminderLeadMinutes: number
  emailReminders: boolean
  notifyEmail: string
  calendarId: string
  calendarName: string
  googleConnected: boolean
  hasWritableCalendar?: boolean
  breakfastEnabled: boolean
  breakfastTime: string
  lunchEnabled: boolean
  lunchTime: string
  dinnerEnabled: boolean
  dinnerTime: string
  mealNotes: string
  sleepTargetHours: number
}

export type SleepStatus = 'unknown' | 'rested' | 'low' | 'deprived'

export interface SleepSession {
  id: string
  start: string
  end: string | null
  source: 'live' | 'manual'
}

export interface SleepSummary {
  asleep: boolean
  sleepingSince: string | null
  sessionId: string | null
  targetHours: number
  status: SleepStatus
  lastSleepHours: number | null
  lastWokeAt: string | null
  hoursAwake: number | null
  sleptLast24h: number
  avgHours7d: number | null
  debtHours: number
  nightsTracked: number
  typicalBedtime: string | null
  typicalWake: string | null
  wakeAnchor: string
  suggestedBedtime: string
  windDownAt: string
  sessions: SleepSession[]
}

export interface CalendarEvent {
  id: string
  summary: string
  description: string
  start: string
  end: string
  allDay: boolean
  createdByCyoa: boolean
}

export interface LinkedCalendar {
  key: string
  calendarId: string
  calendarName: string
  color: string | null
  isDefault: boolean
  readEnabled: boolean
  canWrite: boolean // shared with "Make changes to events"
  readOnly: boolean // user chose "never edit"
  writable: boolean // canWrite && !readOnly
}

export interface CalendarInfo {
  serviceAccountEmail: string
  calendars: LinkedCalendar[]
  maxCalendars: number
  hasWritable: boolean
  pending: { calendarId: string; code: string } | null
}

export interface CalendarLinkResult {
  status: 'linked' | 'verify'
  calendarId: string
  calendarName: string
  code?: string
  message?: string
}

export const KIND_LABEL: Record<OptionKind, string> = {
  yes: 'Yes',
  yes_and: 'Yes, and…',
  no: 'No',
  no_and: 'No, and…',
  route: 'Route',
}

export interface MemoryNote {
  id: string
  text: string
  source: 'user' | 'ai'
  createdAt: string | null
}

export interface AIMemory {
  notes: MemoryNote[]
  log: { at: string; type: string; date: string | null; text: string }[]
}

export interface PlanJob {
  jobId: string
  date: string
  status: 'queued' | 'running' | 'done' | 'error'
  error: string | null
  notifyEmail: boolean
  createdAt: string | null
}
