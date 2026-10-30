import { request } from './client'

export type ServerNotification = { id?: number; message: string }

export async function getNotifications(): Promise<ServerNotification[]> {
  if (!localStorage.getItem('vorona_token')) return []
  const data = await request<{ notifications?: ServerNotification[] }>('/api/notifications')
  return data?.notifications ?? []
}

export async function ackNotifications(ids: number[]): Promise<void> {
  if (!localStorage.getItem('vorona_token') || ids.length === 0) return
  await request<unknown>('/api/notifications/ack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  })
}