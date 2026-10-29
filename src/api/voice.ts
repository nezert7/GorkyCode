import { request } from './client'

// Отправляет запись голоса на сервер и возвращает ответ от нейросети
// Теперь возвращаем объект с текстом и типом операции
export type VoiceResponse = {
  text: string
  operation: string
}

export async function recognizeSpeech(audio: Blob): Promise<VoiceResponse> {
  const body = new FormData()
  body.append('file', audio, 'record.webm')

  const result = await request<{ response: string; operation: string }>('/api/voice-chat', {
    method: 'POST',
    body,
  })

  return {
    text: result.response,
    operation: result.operation, // Передаем на интерфейс тип операции (например, "clarify")
  }
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

// (остальной код файла voice.ts остается без изменений, добавляем только это вниз)

// Тайная отправка текстового ответа, чтобы пропустить уточнение
export async function sendText(text: string): Promise<VoiceResponse> {
  const response = await request<{ response: string; operation: string }>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: text, session_id: 'default' }),
  })

  return {
    text: response.response,
    operation: response.operation,
  }
}