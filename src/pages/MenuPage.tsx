import { useState } from 'react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo'
import crow from '../assets/crow.png'
import crowListening from '../assets/crow-listening.png'
import crowResult from '../assets/crow-result.png'
import listenIcon from '../assets/listen-icon.png'
import listenIconListening from '../assets/listen-icon-listening.png'
import './pages.css'
import './menu-listening.css'
import './menu-result.css'
import './menu-saved.css'

type Mode = 'idle' | 'listening' | 'result' | 'saved'

export default function MenuPage() {
  const [mode, setMode] = useState<Mode>('idle')

  // TODO: текст придёт с бэкенда
  const generatedText = '(Generated text)'

  function handleHeadphones() {
    // TODO: здесь запускать и останавливать запись, когда будет бэкенд
    setMode(mode === 'idle' ? 'listening' : 'result')
  }

  function handleContinue() {
    // TODO: здесь отправлять запись на бэкенд
    setMode('saved')
  }

  const crowByMode = {
    idle: crow,
    listening: crowListening,
    result: crowResult,
    saved: crowListening,
  }
  const crowClass =
    mode === 'idle' ? 'crow crow--menu' : mode === 'saved' ? 'crow crow--saved' : 'crow crow--listening'
  const historyClass =
    mode === 'result'
      ? 'history-link history-link--result'
      : mode === 'saved'
        ? 'history-link history-link--saved'
        : 'history-link'

  return (
    <div className="screen">
      <div className="stage">
        <Logo variant="menu" />

        {(mode === 'idle' || mode === 'listening') && (
          <>
            <button
              className="listen-button"
              aria-label="Слушать"
              aria-pressed={mode === 'listening'}
              onClick={handleHeadphones}
            >
              <img src={mode === 'idle' ? listenIcon : listenIconListening} alt="" />
            </button>
            <p className={mode === 'idle' ? 'menu-caption' : 'menu-caption menu-caption--listening'}>
              {mode === 'idle' ? 'слушаю и напоминаю' : 'слушаю и воспринимаю'}
            </p>
          </>
        )}

        {mode === 'result' && (
          <>
            <div className="result-box">{generatedText}</div>
            <button className="result-action result-action--continue" onClick={handleContinue}>
              продолжить
            </button>
            <button className="result-action result-action--cancel" onClick={() => setMode('idle')}>
              отменить
            </button>
          </>
        )}

        {mode === 'saved' && (
          <>
            <div className="result-box result-box--saved">Запомнила...</div>
            <button className="result-action result-action--home" onClick={() => setMode('idle')}>
              на начало
            </button>
          </>
        )}

        {mode !== 'listening' && (
          <Link to="/history" className={historyClass}>
            история запросов
          </Link>
        )}

        <img src={crowByMode[mode]} alt="" className={crowClass} />
      </div>
    </div>
  )
}
