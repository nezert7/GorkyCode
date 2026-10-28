import { useState } from 'react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo'
import { cancelPending, recognizeSpeech, savePlan } from '../api/voice'
import { useVoiceRecorder } from '../hooks/useVoiceRecorder'
import crow from '../assets/crow.png'
import crowListening from '../assets/crow-listening.png'
import crowResult from '../assets/crow-result.png'
import crowSaved from '../assets/crow-listening.png'
import listenIcon from '../assets/listen-icon.png'
import listenIconListening from '../assets/listen-icon-listening.png'
import './pages.css'
import './menu-listening.css'
import './menu-result.css'
import './menu-saved.css'
import './menu-error.css'

// Состояния одного экрана:
// idle      - ждём нажатия на наушники
// listening - идёт запись (синие наушники)
// result    - показан ответ сервера, кнопки "продолжить" и "отменить"
// saved     - после "продолжить": "Запомнила..."
// error     - что-то пошло не так (в макетах этого экрана нет, пока оформлен как "saved")
type Mode = 'idle' | 'listening' | 'result' | 'saved' | 'error'

function describeError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError') return 'Нет доступа к микрофону'
    if (error.name === 'NotFoundError') return 'Микрофон не найден'
  }
  return 'Что-то пошло не так'
}

export default function MenuPage() {
  const [mode, setMode] = useState<Mode>('idle')
  const [generatedText, setGeneratedText] = useState('')
  const [errorText, setErrorText] = useState('')
  const [busy, setBusy] = useState(false) // true, пока ждём микрофон или сервер
  const { start, stop, cancel } = useVoiceRecorder()

  function fail(error: unknown) {
    cancel()
    setErrorText(describeError(error))
    setMode('error')
  }

  async function handleHeadphones() {
    if (busy) return
    setBusy(true)
    try {
      if (mode === 'idle') {
        await start()
        setMode('listening')
      } else {
        const audio = await stop()
        setGeneratedText(await recognizeSpeech(audio))
        setMode('result')
      }
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleContinue() {
    if (busy) return
    setBusy(true)
    try {
      await savePlan()
      setMode('saved')
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleCancel() {
    setMode('idle')
    try {
      await cancelPending()
    } catch {
      // если сервер не ответил, пользователю это знать не нужно
    }
  }

  const isFinal = mode === 'saved' || mode === 'error'
  const crowByMode = {
    idle: crow,
    listening: crowListening,
    result: crowResult,
    saved: crowSaved,
    error: crowSaved,
  }
  const crowClass =
    mode === 'idle' ? 'crow crow--menu' : isFinal ? 'crow crow--saved' : 'crow crow--listening'
  const historyClass =
    mode === 'result'
      ? 'history-link history-link--result'
      : isFinal
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
              disabled={busy}
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
            <button
              className="result-action result-action--continue"
              disabled={busy}
              onClick={handleContinue}
            >
              продолжить
            </button>
            <button
              className="result-action result-action--cancel"
              disabled={busy}
              onClick={handleCancel}
            >
              отменить
            </button>
          </>
        )}

        {isFinal && (
          <>
            <div className="result-box result-box--saved">
              {mode === 'saved' ? 'Запомнила...' : errorText}
            </div>
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
