import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Logo from '../components/Logo'
import { apiUrl } from '../api/client'
import crow from '../assets/crow.png'
import './pages.css'
import './auth.css'

function checkPassword(password: string, login: string): string | null {
  const issues: string[] = []
  if (password.length < 8) issues.push(`минимум 8 символов (сейчас ${password.length})`)
  if (password.includes(' ')) issues.push('уберите пробелы')
  if (!/[A-ZА-ЯЁ]/.test(password)) issues.push('добавьте заглавную букву')
  if (!/[a-zа-яё]/.test(password)) issues.push('добавьте строчную букву')
  if (!/\d/.test(password)) issues.push('добавьте цифру')
  if (!/[!@#$%^&*()_+\-=[\]{};:'",.<>/?\\|`~]/.test(password)) {
    issues.push('добавьте спецсимвол (!@#$% и т.д.)')
  }
  if (login && password.toLowerCase() === login.trim().toLowerCase()) {
    issues.push('пароль не должен совпадать с логином')
  }
  return issues.length ? `Исправьте пароль: ${issues.join(', ')}` : null
}

// Пиксельный глазик для кнопки показа пароля ("X" - закрашенный пиксель)
const EYE_OPEN = [
  '...XXXXXX...',
  '..X......X..',
  '.X..XXXX..X.',
  'X..XX..XX..X',
  'X..XX..XX..X',
  '.X..XXXX..X.',
  '..X......X..',
  '...XXXXXX...',
]
const EYE_CLOSED = [
  '............',
  'X..........X',
  '.XX......XX.',
  '...XXXXXX...',
  '..X..XX..X..',
  '.X...XX...X.',
  '............',
  '............',
]

function EyeIcon({ open }: { open: boolean }) {
  const rows = open ? EYE_OPEN : EYE_CLOSED
  return (
    <svg viewBox="0 0 12 8" shapeRendering="crispEdges" fill="currentColor" aria-hidden="true">
      {rows.flatMap((row, y) =>
        [...row].map((cell, x) => (cell === 'X' ? <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} /> : null)),
      )}
    </svg>
  )
}

export default function AuthPage() {
  const [isLogin, setIsLogin] = useState(true)
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ login?: string; password?: string; form?: string }>({})
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const loginRef = useRef<HTMLInputElement>(null)
  const passRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const token = localStorage.getItem('vorona_token')
    if (!token) return

    fetch(apiUrl('/api/auth/me'), {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (res.ok) {
          navigate('/start')
        } else {
          localStorage.removeItem('vorona_token')
          localStorage.removeItem('vorona_username')
        }
      })
      .catch(() => {})
  }, [navigate])

  function clearFieldError(field: 'login' | 'password') {
    if (errors.login || errors.password) {
      setErrors({})
    }
    setTimeout(() => {
      if (field === 'login') loginRef.current?.focus()
      else passRef.current?.focus()
    }, 0)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    setErrors({})

    const cleanLogin = login.trim()
    const cleanPassword = password.trim()
    const newErrors: { login?: string; password?: string; form?: string } = {}
    let hasError = false

    if (!cleanLogin) {
      newErrors.login = 'Неверный формат (пустая строка)'
      hasError = true
    } else if (cleanLogin.length < 2) {
      newErrors.login = 'Минимум 2 символа'
      hasError = true
    }

    if (!cleanPassword) {
      newErrors.password = 'Неверный формат'
      hasError = true
    } else if (!isLogin) {
      const passwordMessage = checkPassword(cleanPassword, cleanLogin)
      if (passwordMessage) {
        newErrors.password = 'Слабый пароль'
        newErrors.form = passwordMessage
        hasError = true
      }
    }

    if (hasError) {
      setErrors(newErrors)
      if (newErrors.login) setLogin('')
      if (newErrors.password && !newErrors.form) setPassword('')
      return
    }

    setBusy(true)
    try {
      const endpoint = isLogin ? '/api/auth/login' : '/api/auth/register'
      const res = await fetch(apiUrl(endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: cleanLogin, password: cleanPassword }),
      })

      const data = (await res.json().catch(() => ({}))) as {
        token?: string
        user?: { username?: string }
        detail?: string
      }

      if (!res.ok) {
        const detail = data.detail || 'Ошибка авторизации'
        if (res.status === 409) {
          setErrors({ login: 'Такой логин уже существует', form: detail })
          setLogin('')
        } else if (res.status === 401) {
          setErrors({ password: detail, form: detail })
          setPassword('')
        } else if (detail.toLowerCase().includes('логин')) {
          setErrors({ login: detail, form: detail })
          setLogin('')
        } else {
          setErrors({ password: 'Исправьте пароль', form: detail })
        }
        return
      }

      if (data.token) {
        localStorage.setItem('vorona_token', data.token)
        localStorage.setItem('vorona_username', data.user?.username || cleanLogin)
      }
      navigate('/start')
    } catch {
      setErrors({ password: 'Сервер недоступен' })
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  function toggleMode() {
    setIsLogin(!isLogin)
    setShowPassword(false)
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
            <div className="auth-row" onMouseDown={() => clearFieldError('login')}>
              <label>Логин:</label>
              <input
                ref={loginRef}
                type="text"
                value={login}
                onFocus={() => errors.login && setErrors({ ...errors, login: undefined })}
                onChange={(e) => {
                  if (errors.login) setErrors({ ...errors, login: undefined })
                  setLogin(e.target.value)
                }}
                placeholder={errors.login || ''}
                className={errors.login ? 'input-error' : ''}
              />
            </div>

            <div className="auth-row" onMouseDown={() => clearFieldError('password')}>
              <label>Пароль:</label>
              <div className="auth-password">
                <input
                  ref={passRef}
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onFocus={() => errors.password && setErrors({ ...errors, password: undefined })}
                  onChange={(e) => {
                    if (errors.password) setErrors({ ...errors, password: undefined })
                    setPassword(e.target.value)
                  }}
                  placeholder={errors.password || ''}
                  className={errors.password ? 'input-error' : ''}
                />
                <button
                  type="button"
                  className="auth-eye"
                  aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                  aria-pressed={showPassword}
                  title={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                  onMouseDown={(e) => {
                    // не сбрасываем ошибку и не уводим фокус из поля
                    e.preventDefault()
                    e.stopPropagation()
                  }}
                  onClick={() => setShowPassword(!showPassword)}
                >
                  <EyeIcon open={!showPassword} />
                </button>
              </div>
            </div>

            {errors.form && <p className="auth-error">{errors.form}</p>}

            <button type="submit" disabled={busy} className="auth-submit">
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