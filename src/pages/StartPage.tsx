import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow.png'
import './pages.css'

export default function StartPage() {
  const navigate = useNavigate()
  const username = localStorage.getItem('vorona_username') || ''

  useEffect(() => {
    if (!localStorage.getItem('vorona_token')) {
      navigate('/')
    }
  }, [navigate])

  function handleLogout() {
    localStorage.removeItem('vorona_token')
    localStorage.removeItem('vorona_username')
  }

  return (
    <div className="screen">
      <div className="stage">
        <Logo variant="start" />

        <Link
          to="/"
          onClick={handleLogout}
          style={{
            position: 'absolute',
            top: 'calc(var(--u) * 16)',
            right: 'calc(var(--u) * 16)',
            fontSize: 'calc(var(--u) * 18)',
            textDecoration: 'underline',
            textDecorationThickness: 'calc(var(--u) * 2)',
            color: 'var(--ink)',
          }}
          title="Выйти из профиля"
        >
          {username ? `[ ${username} — выход ]` : '[ выход ]'}
        </Link>

        <Link to="/menu" className="start-button">
          <span>START</span>
        </Link>
        <p className="start-caption">Я всё помню...</p>

        <img src={crow} alt="" className="crow crow--start" />
      </div>
    </div>
  )
}