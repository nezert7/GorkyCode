import { delay, request, useFakeApi } from './client'

// Отправляет запись голоса на сервер и возвращает распознанный текст
// (он показывается на экране "Generated text").
// ВАЖНО: адрес, имя поля и формат ответа - предположение. Уточните у бэкендера.
export async function recognizeSpeech(audio: Blob): Promise<string> {
  if (useFakeApi) {
    // Так можно проверить, что запись действительно работает (консоль: F12)
    console.log('Записано:', audio.size, 'байт, формат', audio.type)
    await delay(800)
    return '(Generated text)'
  }
  const body = new FormData()
  body.append('audio', audio, 'record.webm')
  const result = await request<{ text: string }>('/recognize', { method: 'POST', body })
  return result.text
}

// Сохраняет запись после нажатия на "продолжить" (экран "Запомнила...").
// ВАЖНО: адрес и формат тела запроса - предположение. Уточните у бэкендера.
export async function savePlan(text: string): Promise<void> {
  if (useFakeApi) {
    await delay(500)
    return
  }
  await request<void>('/plans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}
