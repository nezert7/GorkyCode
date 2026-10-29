// Адрес сервера берётся из файла .env (переменная VITE_API_URL).
// Если переменной нет, запросы идут на тот же адрес, с которого открыт сайт
// (так работает интерфейс, который раздаёт сам сервер из папки static_frontend).
const baseUrl: string = import.meta.env.VITE_API_URL || ''

// Оставлено для совместимости: true, если адрес сервера не задан. Запросы это больше не блокирует.
export const useFakeApi = !baseUrl

// Пауза для имитации ответа сервера
export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const apiUrl = (path: string) => `${baseUrl}${path}`

// Общая функция запроса: все обращения к серверу идут через неё
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init)
  if (!response.ok) {
    throw new Error(`Сервер ответил ошибкой ${response.status}`)
  }
  const text = await response.text()
  const data = (text ? JSON.parse(text) : undefined) as T
  playReplyAudio(data)
  return data
}

// Если сервер прислал озвучку ответа (поле audio_url), проигрываем её
function playReplyAudio(data: unknown) {
  if (typeof data !== 'object' || data === null) return
  const url = (data as { audio_url?: unknown }).audio_url
  if (typeof url !== 'string' || !url) return
  // ?t=... нужен, чтобы браузер не брал старую запись из кэша
  new Audio(`${apiUrl(url)}?t=${Date.now()}`).play().catch(() => {
    // браузер может не разрешить автозапуск звука, это не страшно
  })
}
