import { request } from './client'

export type VoiceResponse = {
  text: string
  operation: string
}

export async function recognizeSpeech(audio: Blob): Promise<VoiceResponse> {
  const body = new FormData()
  body.append('file', audio, 'record.webm')

  const result = await request<{ response?: string; spoken_text?: string; operation?: string }>(
    '/api/voice-chat',
    {
      method: 'POST',
      body,
    },
  )

  return {
    text: result.response ?? result.spoken_text ?? '',
    operation: result.operation ?? '',
  }
}

export async function savePlan(): Promise<void> {
  await request<void>('/api/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
}

export async function cancelPending(): Promise<void> {
  await request<void>('/api/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
}

export async function sendText(text: string): Promise<VoiceResponse> {
  const response = await request<{ response?: string; spoken_text?: string; operation?: string }>(
    '/api/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: text, session_id: 'default' }),
    },
  )

  return {
    text: response.response ?? response.spoken_text ?? '',
    operation: response.operation ?? '',
  }
}