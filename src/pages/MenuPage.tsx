import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo'
import { acknowledgeTurn, cancelPending, recognizeSpeech, savePlan, type VoiceResponse } from '../api/voice'
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

type Mode = 'idle' | 'listening' | 'result' | 'saved' | 'error'

function describeError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError') return 'Нет доступа к микрофону'
    if (error.name === 'NotFoundError') return 'Микрофон не найден'
  }
  if (error instanceof Error && error.message) return error.message
  return 'Что-то пошло не так'
}

function getFontSize(text: string): string {
  const len = text.length
  if (len > 140) return 'calc(var(--u) * 16)'
  if (len > 80) return 'calc(var(--u) * 20)'
  if (len > 40) return 'calc(var(--u) * 24)'
  return 'calc(var(--u) * 32)'
}

const actionsRowStyle: CSSProperties = {
  position: 'absolute',
  left: 'calc(var(--u) * 72)',
  top: 'calc(var(--u) * 699)',
  width: 'calc(var(--u) * 655)',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
}

const inlineActionBtnStyle: CSSProperties = {
  position: 'static',
  fontSize: 'calc(var(--u) * 24)',
}

export default function MenuPage() {
  const [mode, setMode] = useState<Mode>('idle')
  const [generatedText, setGeneratedText] = useState('')
  const [operation, setOperation] = useState('')
  const [needsConfirm, setNeedsConfirm] = useState(false)
  const [errorText, setErrorText] = useState('')
  const [busy, setBusy] = useState(false)
  const { start, stop, cancel } = useVoiceRecorder()

  function fail(error: unknown) {
    cancel()
    setErrorText(describeError(error))
    setMode('error')
  }

  function showVoice(res: VoiceResponse) {
    setGeneratedText(res.text)
    setOperation(res.operation)
    setNeedsConfirm(res.requiresConfirmation)
    setMode('result')
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
        showVoice(await recognizeSpeech(audio))
      }
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleSave() {
    if (busy) return
    setBusy(true)
    try {
      const res = await savePlan()
      setGeneratedText(res.text || 'Зафиксировано.')
      setNeedsConfirm(false)
      setMode('saved')
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleReply() {
    if (busy) return
    setBusy(true)
    try {
      await start()
      setMode('listening')
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleCancel() {
    if (busy) return
    setBusy(true)
    try {
      const res = await cancelPending()
      setGeneratedText(res.text)
      setNeedsConfirm(false)
      setOperation('cancel')
      setMode('saved')
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleDone() {
    try {
      await acknowledgeTurn()
    } catch {
    }
    setMode('idle')
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

        {mode === 'result' && needsConfirm && (
          <>
            <div className="result-box" style={{ fontSize: getFontSize(generatedText) }}>
              {generatedText}
            </div>

            <div style={actionsRowStyle}>
              <button
                className="result-action"
                style={inlineActionBtnStyle}
                disabled={busy}
                onClick={handleSave}
              >
                сохранить
              </button>
              <button
                className="result-action"
                style={inlineActionBtnStyle}
                disabled={busy}
                onClick={handleReply}
              >
                изменить
              </button>
              <button
                className="result-action"
                style={inlineActionBtnStyle}
                disabled={busy}
                onClick={handleCancel}
              >
                отменить
              </button>
            </div>
          </>
        )}

        {mode === 'result' && !needsConfirm && operation === 'update' && (
          <>
            <div className="result-box" style={{ fontSize: getFontSize(generatedText) }}>
              {generatedText}
            </div>

            <div style={actionsRowStyle}>
              <button
                className="result-action"
                style={inlineActionBtnStyle}
                disabled={busy}
                onClick={handleCancel}
              >
                откатить
              </button>
              <button
                className="result-action"
                style={inlineActionBtnStyle}
                disabled={busy}
                onClick={handleDone}
              >
                готово
              </button>
            </div>
          </>
        )}

        {mode === 'result' && !needsConfirm && operation !== 'update' && (
          <>
            <div className="result-box" style={{ fontSize: getFontSize(generatedText) }}>
              {generatedText}
            </div>
            <button className="result-action result-action--home" disabled={busy} onClick={handleDone}>
              на начало
            </button>
          </>
        )}

        {isFinal && (
          <>
            <div
              className="result-box result-box--saved"
              style={{ fontSize: getFontSize(mode === 'saved' ? generatedText : errorText) }}
            >
              {mode === 'saved' ? generatedText : errorText}
            </div>
            <button className="result-action result-action--home" onClick={() => setMode('idle')}>
              на начало
            </button>
          </>
        )}

        {mode !== 'listening' && (
          <Link to="/history" className={historyClass}>
            сохранённые запросы
          </Link>
        )}

        <img src={crowByMode[mode]} alt="" className={crowClass} />
      </div>
    </div>
  )
}