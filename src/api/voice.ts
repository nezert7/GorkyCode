import { request } from './client'

// Отправляет запись голоса на сервер и возвращает ответ от нейросети
export async function recognizeSpeech(audio: Blob): Promise<string> {
  const body = new FormData()

  // В main.py бэкенд ждет файл именно под именем 'file'
  body.append('file', audio, 'record.webm')

  // Отправляем на правильный эндпоинт FastAPI
  const result = await request<{ response: string }>('/api/voice-chat', {
    method: 'POST',
    body,
  })

  // Бэкенд возвращает текстовый ответ в поле response
  return result.response
}

// Сохраняет запись после нажатия на "продолжить"
export async function savePlan(): Promise<void> {
  // Бэкенду нужен только ID сессии для подтверждения
  await request<void>('/api/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
}

// Отменяет запись после нажатия на "отменить": сервер перестаёт ждать подтверждения
export async function cancelPending(): Promise<void> {
  await request<void>('/api/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
}
