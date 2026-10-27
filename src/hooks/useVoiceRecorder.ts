import { useCallback, useEffect, useRef } from 'react'

export function useVoiceRecorder() {
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const cancel = useCallback(() => {
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop())
    recorderRef.current = null
  }, [])

  useEffect(() => cancel, [cancel])

  const start = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const recorder = new MediaRecorder(stream)
    chunksRef.current = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data)
    }
    recorder.start()
    recorderRef.current = recorder
  }, [])

  const stop = useCallback(
    () =>
      new Promise<Blob>((resolve, reject) => {
        const recorder = recorderRef.current
        if (!recorder || recorder.state === 'inactive') {
          reject(new Error('Запись не была начата'))
          return
        }
        recorder.onstop = () => {
          const audio = new Blob(chunksRef.current, { type: recorder.mimeType })
          cancel()
          resolve(audio)
        }
        recorder.stop()
      }),
    [cancel],
  )

  return { start, stop, cancel }
}
