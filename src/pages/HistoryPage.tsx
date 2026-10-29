import { useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow-listening.png'
import {
  deletePlan,
  getPlans,
  listPlans,
  markDone,
  planTypeLabels,
  searchPlans,
  toInputDate,
  updatePlan,
  type Plan,
  type PlanType,
} from '../api/history'
import './pages.css'
import './history.css'

type Loaded = { key: string; plans: Plan[] | null }
// Черновик записи, которую сейчас редактируют
type Draft = { text: string; date: string; time: string; type: PlanType }

const planTypes = Object.keys(planTypeLabels) as PlanType[]

// Общий вид полей и кнопок на этом экране
const controlStyle: CSSProperties = {
  fontFamily: 'inherit',
  fontSize: '11px',
  padding: '4px 6px',
  border: '2px solid var(--ink)',
  background: '#fff',
}
const buttonStyle: CSSProperties = { ...controlStyle, padding: '4px 8px', cursor: 'pointer' }
const smallButtonStyle: CSSProperties = { ...controlStyle, padding: '2px 5px', cursor: 'pointer' }

// Цвет подписи типа записи
const typeColors: Record<PlanType, string> = {
  task: '#555',
  meeting: '#24316c',
  reminder: '#8a4b00',
}

export default function HistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const from = searchParams.get('from') ?? undefined
  const to = searchParams.get('to') ?? undefined
  const query = searchParams.get('q')?.trim() ?? ''
  const typeFilter = (searchParams.get('type') as PlanType | null) ?? undefined
  const key = searchParams.toString()
  const isFiltered = Boolean(query || from || to || typeFilter)

  const [searchInput, setSearchInput] = useState(query)
  const [result, setResult] = useState<Loaded | null>(null)
  const [reloads, setReloads] = useState(0) // растёт после изменений, чтобы перечитать список
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>({ text: '', date: '', time: '', type: 'task' })
  const [actionFailed, setActionFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const loadData = async () => {
      let data: Plan[] = []
      if (query) {
        data = await searchPlans(query)
      } else if (from || to) {
        data = await listPlans({ from, to })
      } else {
        data = await getPlans()
      }

      if (typeFilter) {
        data = data.filter((p) => p.type === typeFilter)
      }
      return data
    }

    loadData()
      .then((plans) => !cancelled && setResult({ key, plans }))
      .catch(() => !cancelled && setResult({ key, plans: null }))

    return () => {
      cancelled = true
    }
  }, [key, query, from, to, typeFilter, reloads])

  const current = result?.key === key ? result : null

  function handleSearch(e: FormEvent) {
    e.preventDefault()
    const params: Record<string, string> = {}
    if (searchInput.trim()) params.q = searchInput.trim()
    if (typeFilter) params.type = typeFilter
    setSearchParams(params)
  }

  function handleTypeChange(newType: string) {
    const params: Record<string, string> = {}
    if (query) params.q = query
    if (newType) params.type = newType
    setSearchParams(params)
  }

  function handleReset() {
    setSearchInput('')
    setSearchParams({})
  }

  // Выполняет действие с записью и перечитывает список. Возвращает true, если всё получилось
  async function runAction(action: () => Promise<void>): Promise<boolean> {
    try {
      await action()
      setActionFailed(false)
      setReloads((count) => count + 1)
      return true
    } catch {
      setActionFailed(true)
      return false
    }
  }

  function startEdit(plan: Plan) {
    setEditingId(plan.id)
    setDraft({ text: plan.text, date: toInputDate(plan.date), time: plan.time, type: plan.type })
  }

  async function handleSave() {
    if (editingId === null) return
    if (await runAction(() => updatePlan(editingId, draft))) setEditingId(null)
  }

  function handleDelete(plan: Plan) {
    if (window.confirm(`Удалить запись «${plan.text}»?`)) {
      void runAction(() => deletePlan(plan.id))
    }
  }

  return (
    <div className="screen">
      <div className="stage">
        <Logo variant="menu" />

        <section className="history-box">
          <form onSubmit={handleSearch} style={{ padding: '8px 16px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="поиск (текст, дата, время)..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              style={{ ...controlStyle, flex: '1', minWidth: '150px' }}
            />
            <select value={typeFilter ?? ''} onChange={(e) => handleTypeChange(e.target.value)} style={controlStyle}>
              <option value="">все типы</option>
              {planTypes.map((planType) => (
                <option key={planType} value={planType}>
                  {planTypeLabels[planType]}
                </option>
              ))}
            </select>
            <button type="submit" style={buttonStyle}>
              найти
            </button>
            {isFiltered && (
              <button type="button" onClick={handleReset} style={buttonStyle}>
                сброс
              </button>
            )}
          </form>

          <div className="history-scroll" style={{ top: '75px' }}>
            {actionFailed && <p style={{ marginBottom: '6px' }}>не удалось выполнить действие</p>}

            {!current ? (
              <p>загрузка...</p>
            ) : current.plans === null ? (
              <p>не удалось загрузить</p>
            ) : current.plans.length === 0 ? (
              <p>{isFiltered ? 'ничего не найдено' : 'пока ничего нет'}</p>
            ) : (
              <ul className="history-list">
                {current.plans.map((plan) => {
                  const done = plan.status === 'done'

                  if (editingId === plan.id) {
                    return (
                      <li
                        key={plan.id}
                        className="history-row"
                        style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}
                      >
                        <input
                          type="date"
                          value={draft.date}
                          onChange={(e) => setDraft({ ...draft, date: e.target.value })}
                          style={controlStyle}
                        />
                        <input
                          type="time"
                          value={draft.time}
                          onChange={(e) => setDraft({ ...draft, time: e.target.value })}
                          style={controlStyle}
                        />
                        <select
                          value={draft.type}
                          onChange={(e) => setDraft({ ...draft, type: e.target.value as PlanType })}
                          style={controlStyle}
                        >
                          {planTypes.map((planType) => (
                            <option key={planType} value={planType}>
                              {planTypeLabels[planType]}
                            </option>
                          ))}
                        </select>
                        <input
                          type="text"
                          value={draft.text}
                          onChange={(e) => setDraft({ ...draft, text: e.target.value })}
                          style={{ ...controlStyle, flex: '1', minWidth: '200px' }}
                        />
                        <button type="button" onClick={handleSave} style={buttonStyle}>
                          сохранить
                        </button>
                        <button type="button" onClick={() => setEditingId(null)} style={buttonStyle}>
                          отмена
                        </button>
                      </li>
                    )
                  }

                  return (
                    <li
                      key={plan.id}
                      className="history-row"
                      style={{ display: 'flex', gap: '15px', alignItems: 'center', opacity: done ? 0.55 : 1 }}
                    >
                      <span style={{ minWidth: '85px' }}>{plan.date || 'без даты'}</span>
                      <span style={{ minWidth: '45px' }}>{plan.time || '—'}</span>
                      <span style={{ fontSize: '11px', color: typeColors[plan.type], minWidth: '80px' }}>
                        [{planTypeLabels[plan.type] || plan.type}]
                      </span>
                      <span style={{ flex: 1, textDecoration: done ? 'line-through' : 'none' }}>
                        {done ? '[✓ Выполнено] ' : ''}
                        {plan.text}
                      </span>
                      <button
                        type="button"
                        title="Отметить выполненной"
                        disabled={done}
                        onClick={() => void runAction(() => markDone(plan.id))}
                        style={{ ...smallButtonStyle, opacity: done ? 0.4 : 1 }}
                      >
                        ✓
                      </button>
                      <button type="button" title="Изменить" onClick={() => startEdit(plan)} style={smallButtonStyle}>
                        ✎
                      </button>
                      <button
                        type="button"
                        title="Удалить из списка и календаря"
                        onClick={() => handleDelete(plan)}
                        style={smallButtonStyle}
                      >
                        ✕
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </section>

        <Link to="/menu" className="home-link">
          на начало
        </Link>

        <img src={crow} alt="" className="crow crow--history" />
      </div>
    </div>
  )
}
