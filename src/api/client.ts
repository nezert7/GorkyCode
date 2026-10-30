const baseUrl: string = import.meta.env.VITE_API_URL || ''

export const useFakeApi = !baseUrl
export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
export const apiUrl = (path: string) => `${baseUrl}${path}`

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('vorona_token') || ''
  const headers = new Headers(init.headers || {})

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(apiUrl(path), { ...init, headers })

  if (response.status === 401) {
    localStorage.removeItem('vorona_token')
    localStorage.removeItem('vorona_username')
    if (!window.location.hash.endsWith('#/')) {
      window.location.hash = '#/'
    }
    throw new Error('Необходима авторизация')
  }

  if (!response.ok) {
    let detail = `Сервер ответил ошибкой ${response.status}`
    try {
      const errData = (await response.json()) as { detail?: string }
      if (errData?.detail) detail = errData.detail
    } catch {
      // игнорируем ошибку парсинга
    }
    throw new Error(detail)
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
  new Audio(`${apiUrl(url)}?t=${Date.now()}`).play().catch(() => {})
}