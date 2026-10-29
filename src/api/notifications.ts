import { request } from './client'

export type ServerNotification = { message: string }

// Уведомления о наступивших напоминаниях
export async function getNotifications(): Promise<ServerNotification[]> {
  const data = await request<{ notifications?: ServerNotification[] }>('/api/notifications')
  return data?.notifications ?? []
}
