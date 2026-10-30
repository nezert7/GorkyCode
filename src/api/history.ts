import { apiUrl, request } from './client'

export type PlanType = 'task' | 'meeting' | 'reminder'
export type PlanStatus = 'pending' | 'done'

export type Plan = {
  id: number
  date: string
  time: string
  text: string
  type: PlanType
  createdAt: string
  status: PlanStatus
}

export const planTypeLabels: Record<PlanType, string> = {
  task: 'задача',
  meeting: 'встреча',
  reminder: 'напоминание',
}

export const planStatusLabels: Record<PlanStatus, string> = {
  pending: 'не выполнено',
  done: 'выполнено',
}

export type Period = { from?: string; to?: string }

type ServerItem = Record<string, unknown>

function pick(item: ServerItem, keys: string[]): unknown {
  for (const key of keys) {
    const value = item[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

const asString = (value: unknown): string => (value === undefined ? '' : String(value))

function formatDate(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date)
  return match ? `${match[3]}.${match[2]}.${match[1]}` : date
}

export function toInputDate(date: string): string {
  return date.includes('.') ? date.split('.').reverse().join('-') : date
}

function formatTime(time: string): string {
  if (!time) return ''
  const match = /^(\d{2}):(\d{2})/.exec(time)
  return match ? `${match[1]}:${match[2]}` : time.slice(0, 5)
}

function fromServer(raw: ServerItem, index: number): Plan {
  const intent = asString(pick(raw, ['intent', 'type', 'kind'])).toLowerCase()
  const type: PlanType = intent.includes('meet')
    ? 'meeting'
    : intent.includes('remind')
      ? 'reminder'
      : 'task'

  const statusText = asString(pick(raw, ['status', 'state'])).toLowerCase()
  const doneFlag = pick(raw, ['is_done', 'done', 'completed'])
  const status: PlanStatus = statusText === 'done' || doneFlag === true ? 'done' : 'pending'

  const dateRaw = asString(
    pick(raw, ['parsed_date', 'date', 'due_date', 'start_date', 'scheduled_date', 'deadline', 'datetime', 'start', 'due']),
  )
  const timeRaw =
    asString(pick(raw, ['parsed_time', 'time', 'start_time', 'due_time'])) ||
    (/[T ](\d{2}:\d{2})/.exec(dateRaw)?.[1] ?? '')

  const text = asString(
    pick(raw, ['action', 'title', 'text', 'description', 'name', 'content', 'summary', 'task']),
  )
  if (!text) {
    console.warn('Не удалось прочитать запись, пришлите её разработчику:', raw)
  }

  const id = Number(pick(raw, ['id', 'task_id']))

  return {
    id: Number.isNaN(id) ? index : id,
    date: formatDate(dateRaw),
    time: formatTime(timeRaw),
    text,
    type,
    createdAt: asString(pick(raw, ['created_at', 'createdAt', 'created', 'timestamp'])),
    status,
  }
}

async function fetchPlans(path: string): Promise<Plan[]> {
  const data = await request<{ items?: ServerItem[] }>(path)
  return (data?.items ?? []).map(fromServer)
}

export async function getPlans(): Promise<Plan[]> {
  return fetchPlans('/api/history?limit=500&sort_by=created_desc')
}

export async function listPlans(period: Period): Promise<Plan[]> {
  const params = new URLSearchParams({
    start_date: period.from ?? '1900-01-01',
    end_date: period.to ?? '2999-12-31',
    sort_by: 'date',
    status: 'all',
  })
  return fetchPlans(`/api/tasks?${params}`)
}

export async function searchPlans(query: string): Promise<Plan[]> {
  const params = new URLSearchParams({ q: query, limit: '50' })
  return fetchPlans(`/api/search?${params}`)
}

export async function markDone(id: number): Promise<void> {
  await request<unknown>(`/api/tasks/${id}/done`, { method: 'POST' })
}

export type PlanChanges = {
  text: string
  date: string
  time: string
  type: PlanType
}

const serverIntent: Record<PlanType, string> = {
  task: 'Task',
  meeting: 'Meeting',
  reminder: 'Reminder',
}

function toServerClock(value: string): string | null {
  if (!value) return null
  const match = /^(\d{2}):(\d{2})/.exec(value)
  return match ? `${match[1]}:${match[2]}` : null
}

export async function updatePlan(id: number, changes: PlanChanges): Promise<void> {
  await request<unknown>(`/api/tasks/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action: changes.text,
      parsed_date: changes.date || null,
      parsed_time: toServerClock(changes.time),
      intent: serverIntent[changes.type],
    }),
  })
}

export async function deletePlan(id: number): Promise<void> {
  await request<unknown>(`/api/tasks/${id}`, { method: 'DELETE' })
}

export async function downloadCalendar(): Promise<void> {
  const token = localStorage.getItem('vorona_token') || ''
  const response = await fetch(apiUrl('/api/calendar.ics'), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (response.status === 401) {
    localStorage.removeItem('vorona_token')
    localStorage.removeItem('vorona_username')
    if (!window.location.hash.endsWith('#/')) window.location.hash = '#/'
    throw new Error('Необходима авторизация')
  }
  if (!response.ok) throw new Error('Не удалось скачать календарь')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'vorona.ics'
  link.click()
  URL.revokeObjectURL(url)
}