import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow-listening.png'
import { getPlans, listPlans, searchPlans, planTypeLabels, type Plan, type PlanType } from '../api/history'
import './pages.css'
import './history.css'

type Loaded = { key: string; plans: Plan[] | null }

export default function HistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const from = searchParams.get('from') ?? undefined
  const to = searchParams.get('to') ?? undefined
  const query = searchParams.get('q')?.trim() ?? ''
  const typeFilter = searchParams.get('type') as PlanType | undefined
  const key = searchParams.toString()
  const isFiltered = Boolean(query || from || to || typeFilter)

  const [searchInput, setSearchInput] = useState(query)
  const [result, setResult] = useState<Loaded | null>(null)

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
  }, [key, query, from, to, typeFilter])

  const current = result?.key === key ? result : null

  function handleSearch(e: React.FormEvent) {
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
              style={{
                fontFamily: 'inherit',
                fontSize: '11px',
                padding: '4px 6px',
                border: '2px solid var(--ink)',
                flex: '1',
                minWidth: '150px',
              }}
            />
            <select
              value={typeFilter ?? ''}
              onChange={(e) => handleTypeChange(e.target.value)}
              style={{
                fontFamily: 'inherit',
                fontSize: '11px',
                padding: '4px 6px',
                border: '2px solid var(--ink)',
                background: '#fff',
              }}
            >
              <option value="">все типы</option>
              <option value="task">задача</option>
              <option value="meeting">встреча</option>
              <option value="reminder">напоминание</option>
            </select>
            <button
              type="submit"
              style={{
                fontFamily: 'inherit',
                fontSize: '11px',
                padding: '4px 8px',
                border: '2px solid var(--ink)',
                cursor: 'pointer',
                background: '#fff',
              }}
            >
              найти
            </button>
            {isFiltered && (
              <button
                type="button"
                onClick={handleReset}
                style={{
                  fontFamily: 'inherit',
                  fontSize: '11px',
                  padding: '4px 8px',
                  border: '2px solid var(--ink)',
                  cursor: 'pointer',
                  background: '#fff',
                }}
              >
                сброс
              </button>
            )}
          </form>

          <div className="history-scroll" style={{ top: '75px' }}>
            {!current ? (
              <p>загрузка...</p>
            ) : current.plans === null ? (
              <p>не удалось загрузить</p>
            ) : current.plans.length === 0 ? (
              <p>{isFiltered ? 'ничего не найдено' : 'пока ничего нет'}</p>
            ) : (
              <ul className="history-list">
                {current.plans.map((plan) => (
                  <li key={plan.id} className="history-row" style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
                    <span style={{ minWidth: '85px' }}>{plan.date}</span>
                    <span style={{ minWidth: '45px' }}>{plan.time || '—'}</span>
                    <span style={{ fontSize: '11px', color: '#555', minWidth: '80px' }}>
                      [{planTypeLabels[plan.type] || plan.type}]
                    </span>
                    <span style={{ flex: 1 }}>{plan.text}</span>
                  </li>
                ))}
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