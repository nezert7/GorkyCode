export type Plan = {
  id: number
  date: string // например, "30.10.2007"
  time: string // "10:00" или пустая строка, если времени нет
  text: string
}

// Пока бэкенда нет, возвращаем заготовленные данные.
// Когда он появится, достаточно заменить тело функции на настоящий запрос:
//   const response = await fetch(`${import.meta.env.VITE_API_URL}/plans`)
//   return response.json()
// Остальной код приложения менять не придётся.
export async function getPlans(): Promise<Plan[]> {
  return [
    { id: 1, date: '29.10.2007', time: '', text: 'Поздравить Ярика с ДР' },
    { id: 2, date: '30.10.2007', time: '10:00', text: 'Встреча с преподом' },
    { id: 3, date: '30.10.2007', time: '12:00', text: 'Встреча с учебным офисом' },
    { id: 4, date: '30.10.2007', time: '13:00', text: 'Психолог после встречи с учебным офисом' },
    { id: 5, date: '31.10.2007', time: '', text: 'Победить в конкурсе на хэллоуин' },
  ]
}
