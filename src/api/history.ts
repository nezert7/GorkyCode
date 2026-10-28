import { request, useFakeApi } from './client'

export type PlanType = 'task' | 'meeting' | 'reminder'
export type PlanStatus = 'pending' | 'done'

export type Plan = {
  id: number
  date: string // на какую дату запись, показывается как "30.10.2007"
  time: string // "10:00" или пустая строка, если времени нет
  text: string
  type: PlanType
  createdAt: string // когда запись создана
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

// Период для выборки: даты в формате "2007-10-30", границы включаются.
// Можно указать только одну границу.
export type Period = { from?: string; to?: string }

// ---------- Перевод записей из БД в формат интерфейса ----------

type ServerItem = Record<string, unknown>

// Берёт значение первого поля из списка, которое есть в записи
function pick(item: ServerItem, keys: string[]): unknown {
  for (const key of keys) {
    const value = item[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

const asString = (value: unknown): string => (value === undefined ? '' : String(value))

// "2007-10-30" или "2007-10-30T10:00:00" -> "30.10.2007"
function formatDate(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date)
  return match ? `${match[3]}.${match[2]}.${match[1]}` : date
}

// "10:00:00" -> "10:00". "00:00" считаем отсутствием времени
function formatTime(time: string): string {
  const short = time.slice(0, 5)
  return short === '00:00' ? '' : short
}

// ВАЖНО: названия полей в БД я не видел (файла database.py у меня нет), поэтому ниже
// перечислены вероятные варианты. Если в консоли браузера (F12) появится предупреждение
// "Не удалось прочитать запись", пришлите его, и я подставлю точные названия.
// ВАЖНО: Добавлены правильные названия полей из твоего database.py: 'action', 'parsed_date', 'parsed_time'
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

  // Сюда добавили 'parsed_date' и 'parsed_time'
  const dateRaw = asString(pick(raw, ['parsed_date', 'date', 'due_date', 'start_date', 'scheduled_date', 'deadline', 'datetime', 'start', 'due']))
  const timeRaw =
    asString(pick(raw, ['parsed_time', 'time', 'start_time', 'due_time'])) || (/[T ](\d{2}:\d{2})/.exec(dateRaw)?.[1] ?? '')

  // Сюда добавили 'action' (так колонка называется в твоей SQLite)
  const text = asString(pick(raw, ['action', 'title', 'text', 'description', 'name', 'content', 'summary', 'task']))
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

// ---------- Запросы к серверу ----------

// Убрали блок if (useFakeApi), чтобы запрос реально улетал на сервер
async function fetchPlans(path: string): Promise<Plan[]> {
  const data = await request<{ items?: ServerItem[] }>(path)
  return (data.items ?? []).map(fromServer)
}

// Все записи (экран "история запросов"). Сервер отдаёт максимум 200 за раз.
export async function getPlans(): Promise<Plan[]> {
  return fetchPlans('/api/history?limit=200&sort_by=date')
}

// Задачи и встречи за период. Сервер требует начало периода,
// поэтому недостающую границу заменяем очень ранней или очень поздней датой.
export async function listPlans(period: Period): Promise<Plan[]> {
  const params = new URLSearchParams({
    start_date: period.from ?? '1900-01-01',
    end_date: period.to ?? '2999-12-31',
    sort_by: 'date',
  })
  return fetchPlans(`/api/tasks?${params}`)
}

// Поиск по запросу пользователя. Отдельного адреса для поиска на сервере нет,
// поэтому берём записи и ищем среди них здесь: по тексту, дате, времени и типу.
// Когда бэкендер добавит настоящий поиск, заменить нужно только эту функцию.
export async function searchPlans(query: string): Promise<Plan[]> {
  const plans = await getPlans()
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return plans
  return plans.filter((plan) => {
    const haystack = `${plan.text} ${plan.date} ${plan.time} ${planTypeLabels[plan.type]}`.toLowerCase()
    return words.every((word) => haystack.includes(word))
  })
}
