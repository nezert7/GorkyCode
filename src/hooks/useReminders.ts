import { useEffect } from 'react'
import { getNotifications } from '../api/notifications'

export function useReminders() {
  useEffect(() => {
    if (!('Notification' in window)) return

    const timer = window.setInterval(async () => {
      try {
        for (const item of await getNotifications()) {
          if (Notification.permission === 'granted') {
            new Notification('Ворона', { body: item.message })
          } else if (Notification.permission !== 'denied') {
            void Notification.requestPermission()
          }
        }
      } catch {
      }
    }, 30000)

    return () => window.clearInterval(timer)
  }, [])
}
