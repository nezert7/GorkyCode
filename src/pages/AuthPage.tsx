import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow.png'
import './pages.css'
import './auth.css'

export default function AuthPage() {

  const [isLogin, setIsLogin] = useState(true)
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ login?: string; password?: string }>({})
  
  const navigate = useNavigate()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrors({})
    let hasError = false
    const newErrors: { login?: string; password?: string } = {}

    if (!login.trim()) {
      newErrors.login = 'Неверный формат (пустая строка)'
      hasError = true
    }
    if (!password.trim()) {
      newErrors.password = 'Неверный формат'
      hasError = true
    }

    if (!hasError) {
      if (isLogin && password === 'wrong') {
        newErrors.password = 'Неверный пароль'
        hasError = true
      } else if (!isLogin && login.trim() === 'admin') {
        newErrors.login = 'Такой логин уже существует'
        hasError = true
      }
    }

    if (hasError) {
      setErrors(newErrors)
      if (newErrors.login) setLogin('')
      if (newErrors.password) setPassword('')
      return
    }

    navigate('/start')
  }

  function toggleMode() {
    setIsLogin(!isLogin)
    setErrors({})
    setLogin('')
    setPassword('')
  }

  return (
    <div className="screen">
      <div className="stage">
        <Logo variant="start" />

        <div className="auth-box">
          <h2 className="auth-title">{isLogin ? 'Авторизация' : 'Регистрация'}</h2>
          
          <form onSubmit={handleSubmit} className="auth-form">
            <div className="auth-row">
              <label>Логин:</label>
              <input
                type="text"
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                placeholder={errors.login || ''}
                className={errors.login ? 'input-error' : ''}
              />
            </div>
            
            <div className="auth-row">
              <label>Пароль:</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={errors.password || ''}
                className={errors.password ? 'input-error' : ''}
              />
            </div>
            
            <button type="submit" className="auth-submit">
              {isLogin ? 'Войти' : 'Зарегистрироваться'}
            </button>
          </form>

          <button type="button" className="auth-switch" onClick={toggleMode}>
            {isLogin ? 'Нет аккаунта...' : 'Уже есть аккаунт...'}
          </button>
        </div>

        <p className="start-caption">Я всё помню...</p>
        <img src={crow} alt="" className="crow crow--start" />
      </div>
    </div>
  )
}