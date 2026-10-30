import { Link } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow.png'
import './pages.css'

export default function StartPage() {
  return (
    <div className="screen">
      <div className="stage">
        <Logo variant="start" />

        <Link 
          to="/" 
          style={{
            position: 'absolute',
            top: 'calc(var(--u) * 16)',
            right: 'calc(var(--u) * 16)',
            fontSize: 'calc(var(--u) * 18)',
            textDecoration: 'underline',
            textDecorationThickness: 'calc(var(--u) * 2)',
            color: 'var(--ink)'
          }}
          title="Выйти из профиля"
        >
          [ выход ]
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