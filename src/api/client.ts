// Адрес сервера берётся из файла .env (переменная VITE_API_URL).
// Пока её нет, приложение работает на заготовленных данных (см. функции в этой папке).
const baseUrl = import.meta.env.VITE_API_URL || '';

export const useFakeApi = !baseUrl

// Пауза для имитации ответа сервера
export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// Общая функция запроса: все обращения к серверу идут через неё
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, init)
  if (!response.ok) {
    throw new Error(`Сервер ответил ошибкой ${response.status}`)
  }
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}
