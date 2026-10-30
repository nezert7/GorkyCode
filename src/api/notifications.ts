import { request } from './client'

export type ServerNotification = { message: string }

export async function getNotifications(): Promise<ServerNotification[]> {
  if (!localStorage.getItem('vorona_token')) return []
  const data = await request<{ notifications?: ServerNotification[] }>('/api/notifications')
  return data?.notifications ?? []
}