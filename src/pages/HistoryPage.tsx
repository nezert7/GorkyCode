import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow-listening.png'
import {
  deletePlan,
  downloadCalendar,
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
import './history-tools.css'

type Loaded = { key: string; plans: Plan[] | null }
type Draft = { text: string; date: string; time: string; type: PlanType }

const planTypes = Object.keys(planTypeLabels) as PlanType[]

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
  const [reloads, setReloads] = useState(0)
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
          <form className="history-tools" onSubmit={handleSearch}>
            <input
              type="text"
              placeholder="поиск (текст, дата, время)..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
            <select value={typeFilter ?? ''} onChange={(e) => handleTypeChange(e.target.value)}>
              <option value="">все типы</option>
              {planTypes.map((planType) => (
                <option key={planType} value={planType}>
                  {planTypeLabels[planType]}
                </option>
              ))}
            </select>
            <button type="submit">найти</button>
            <button type="button" onClick={() => void downloadCalendar().catch(() => setActionFailed(true))}>
              календарь
            </button>
            {isFiltered && (
              <button type="button" onClick={handleReset}>
                сброс
              </button>
            )}
          </form>

          <div className="history-scroll">
            {actionFailed && <p className="history-error">не удалось выполнить действие</p>}

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
                      <li key={plan.id} className="history-row history-row--edit">
                        <input
                          type="date"
                          value={draft.date}
                          onChange={(e) => setDraft({ ...draft, date: e.target.value })}
                        />
                        <input
                          type="time"
                          value={draft.time}
                          onChange={(e) => setDraft({ ...draft, time: e.target.value })}
                        />
                        <select
                          value={draft.type}
                          onChange={(e) => setDraft({ ...draft, type: e.target.value as PlanType })}
                        >
                          {planTypes.map((planType) => (
                            <option key={planType} value={planType}>
                              {planTypeLabels[planType]}
                            </option>
                          ))}
                        </select>
                        <input
                          type="text"
                          className="history-edit-text"
                          value={draft.text}
                          onChange={(e) => setDraft({ ...draft, text: e.target.value })}
                        />
                        <button type="button" onClick={handleSave}>
                          сохранить
                        </button>
                        <button type="button" onClick={() => setEditingId(null)}>
                          отмена
                        </button>
                      </li>
                    )
                  }

                  return (
                    <li key={plan.id} className={done ? 'history-row history-row--done' : 'history-row'}>
                      <span className="plan-date">{plan.date || 'без даты'}</span>
                      <span className="plan-time">{plan.time || '—'}</span>
                      <span className={`plan-type plan-type--${plan.type}`}>
                        [{planTypeLabels[plan.type] || plan.type}]
                      </span>
                      <span className="plan-text">
                        {done ? '[✓ Выполнено] ' : ''}
                        {plan.text}
                      </span>
                      <button
                        type="button"
                        className={done ? 'history-icon history-icon--done' : 'history-icon'}
                        title={done ? 'Вернуть в невыполненные' : 'Отметить выполненной'}
                        onClick={() => void runAction(() => markDone(plan.id))}
                      >
                        ✓
                      </button>
                      <button
                        type="button"
                        className="history-icon"
                        title="Изменить"
                        onClick={() => startEdit(plan)}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        className="history-icon"
                        title="Удалить из списка и календаря"
                        onClick={() => handleDelete(plan)}
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