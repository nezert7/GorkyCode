import { useEffect, useState } from 'react'
import { ackNotifications, getNotifications } from '../api/notifications'

export function Reminders() {
  const [notes, setNotes] = useState<string[]>([])

  useEffect(() => {
    let stopped = false

    const pull = async () => {
      try {
        const items = await getNotifications()
        if (stopped || items.length === 0) return

        setNotes((prev) => [...items.map((item) => item.message), ...prev].slice(0, 4))

        if ('Notification' in window && Notification.permission === 'granted') {
          for (const item of items) {
            new Notification('Ворона', { body: item.message })
          }
        }

        const ids = items
          .map((item) => item.id)
          .filter((id): id is number => typeof id === 'number')
        await ackNotifications(ids)
      } catch {
        // нет сети или пользователь ещё не вошёл
      }
    }

    void pull()
    const timer = window.setInterval(() => void pull(), 30000)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [])

  if (notes.length === 0) return null

  return (
    <div className="reminder-stack">
      {notes.map((text, index) => (
        <button
          key={`${text}-${index}`}
          type="button"
          className="reminder-toast"
          onClick={() => setNotes((prev) => prev.filter((_, noteIndex) => noteIndex !== index))}
        >
          {text}
        </button>
      ))}
    </div>
  )
}