import { request, useFakeApi } from './client'

export type Plan = {
  id: number
  date: string 
  time: string 
  text: string
}

const fakePlans: Plan[] = [
  { id: 1, date: '29.10.2007', time: '', text: 'Поздравить Ярика с ДР' },
  { id: 2, date: '30.10.2007', time: '10:00', text: 'Встреча с преподом' },
  { id: 3, date: '30.10.2007', time: '12:00', text: 'Встреча с учебным офисом' },
  { id: 4, date: '30.10.2007', time: '13:00', text: 'Психолог после встречи с учебным офисом' },
  { id: 5, date: '31.10.2007', time: '', text: 'Победить в конкурсе на хэллоуин' },
]


// адрес и формат ответа ниже - предположение. бэкенд, поправь.
export async function getPlans(): Promise<Plan[]> {
  if (useFakeApi) return fakePlans
  return request<Plan[]>('/plans')
}
