const baseUrl: string = import.meta.env.VITE_API_URL || ''

export const useFakeApi = !baseUrl

export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const apiUrl = (path: string) => `${baseUrl}${path}`

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

function playReplyAudio(data: unknown) {
  if (typeof data !== 'object' || data === null) return
  const url = (data as { audio_url?: unknown }).audio_url
  if (typeof url !== 'string' || !url) return
  new Audio(`${apiUrl(url)}?t=${Date.now()}`).play().catch(() => {
  })
}
