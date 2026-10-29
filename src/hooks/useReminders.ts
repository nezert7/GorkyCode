import { useEffect } from 'react'
import { getNotifications } from '../api/notifications'

// Раз в 30 секунд спрашивает у сервера, не пора ли о чём-то напомнить,
// и показывает системное уведомление. Подключается один раз, в App.tsx.
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
        // сервер недоступен, попробуем в следующий раз
      }
    }, 30000)

    return () => window.clearInterval(timer)
  }, [])
}
