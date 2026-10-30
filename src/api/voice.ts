import { request } from './client'

export type VoiceResponse = {
  text: string
  operation: string
  requiresConfirmation: boolean
  uiStatus: string
}

type ServerVoice = {
  response?: string
  spoken_text?: string
  operation?: string
  requires_confirmation?: boolean
  ui_status?: string
}

function mapVoice(result: ServerVoice): VoiceResponse {
  const operation = result.operation ?? ''
  return {
    text: result.response ?? result.spoken_text ?? '',
    operation,
    requiresConfirmation:
      Boolean(result.requires_confirmation) || operation === 'create' || operation === 'clarify',
    uiStatus: result.ui_status ?? '',
  }
}

export async function recognizeSpeech(audio: Blob): Promise<VoiceResponse> {
  const body = new FormData()
  body.append('file', audio, 'record.webm')

  const result = await request<ServerVoice>('/api/voice-chat', {
    method: 'POST',
    body,
  })

  return mapVoice(result)
}

export async function savePlan(): Promise<VoiceResponse> {
  const result = await request<ServerVoice>('/api/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
  return mapVoice(result)
}

export async function cancelPending(): Promise<VoiceResponse> {
  const result = await request<ServerVoice>('/api/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
  return mapVoice(result)
}

export async function acknowledgeTurn(): Promise<void> {
  await request<unknown>('/api/ack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
}

export async function sendText(text: string): Promise<VoiceResponse> {
  const response = await request<ServerVoice>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: text, session_id: 'default' }),
  })

  return mapVoice(response)
}