import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow-listening.png'
import { getPlans, type Plan } from '../api/history'
import './pages.css'
import './history.css'

export default function HistoryPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null) 
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getPlans()
      .then(setPlans)
      .catch(() => setFailed(true))
  }, [])

  return (
    <div className="screen">
      <div className="stage">
        <Logo variant="menu" />

        <section className="history-box">
          <h2 className="history-title">Планы птичьего полёта</h2>

          <div className="history-scroll">
            {failed ? (
              <p>не удалось загрузить</p>
            ) : plans === null ? (
              <p>загрузка...</p>
            ) : plans.length === 0 ? (
              <p>пока ничего нет</p>
            ) : (
              <ul className="history-list">
                {plans.map((plan) => (
                  <li key={plan.id} className="history-row">
                    <span>{plan.date}</span>
                    <span>{plan.time}</span>
                    <span>{plan.text}</span>
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
