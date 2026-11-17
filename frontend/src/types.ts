export type GoalStatus = 'backlog' | 'todo' | 'doing' | 'done'
export type Priority = 'high' | 'medium' | 'low'
export type OptionKind = 'yes' | 'yes_and' | 'no' | 'no_and' | 'route'
export type ChapterSource = 'calendar' | 'goal' | 'custom'

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
}

export interface Chapter {
  id: string
  start: string
  end: string
  title: string
  priority: Priority
  source: ChapterSource
  calendarEventId: string | null
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

export interface DayPlan {
  date: string
  priorities: string
  dayStart: string
  dayEnd: string
  summary: string
  storylines: Storyline[]
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
  googleConnected: boolean
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

export interface CalendarInfo {
  id: string
  summary: string
  primary: boolean
}

export const KIND_LABEL: Record<OptionKind, string> = {
  yes: 'Yes',
  yes_and: 'Yes, and…',
  no: 'No',
  no_and: 'No, and…',
  route: 'Route',
}
