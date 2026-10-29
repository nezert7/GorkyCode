import os
import wave
import logging
import asyncio
import edge_tts
import sounddevice as sd
import numpy as np
from typing import Tuple, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

try:
    import av
    _orig_av_open = av.open

    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)

    av.open = _safe_av_open
except Exception:
    pass

try:
    from faster_whisper import WhisperModel
    import faster_whisper.audio
    if hasattr(faster_whisper.audio, "av"):
        faster_whisper.audio.av.open = _safe_av_open

    whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    print("✅ [STT] Локальная модель faster-whisper (base) загружена.")
except Exception as e:
    whisper_model = None
    print(f"⚠️ [STT] faster-whisper не загружен ({e}), используется облачный резерв.")


class VoiceService:
    def __init__(self, voice: str = "ru-RU-SvetlanaNeural"):
        self.voice = voice

    @staticmethod
    def get_audio_duration(file_path: str) -> float:
        try:
            with wave.open(file_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return frames / float(rate)
        except Exception:
            pass
        try:
            size_bytes = os.path.getsize(file_path)
            return max(0.6, size_bytes / 16000.0) if size_bytes > 1500 else 0.2
        except Exception:
            return 2.0

    @staticmethod
    def _cloud_whisper_fallback(file_path: str) -> str:
        groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
        if not groq_key:
            return ""
        try:
            from agent_core import get_shared_agent
            http_client = get_shared_agent().http_client
            client = OpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                http_client=http_client
            )
            with open(file_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=audio_file,
                    language="ru"
                )
            return (transcription.text or "").strip()
        except Exception as exc:
            logging.error(f"Cloud STT fallback failed: {exc}")
            return ""

    def record_and_transcribe(self, duration_sec: int = 5, sample_rate: int = 16000) -> Tuple[str, float]:
        if whisper_model is None:
            raise RuntimeError("faster-whisper не загружен или не установлен.")

        print(f"[*] Запись голоса ({duration_sec} сек)...")
        audio_data = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32"
        )
        sd.wait()

        audio_data = audio_data.flatten()
        segments, _ = whisper_model.transcribe(audio_data, language="ru", beam_size=5)
        text = " ".join([segment.text for segment in segments]).strip()
        return text, float(duration_sec)

    def transcribe_audio_file(self, file_path: str) -> Tuple[str, float]:
        duration_sec = self.get_audio_duration(file_path)
        print(f"🎙 [STT] Получен аудиофайл: {file_path} (~{duration_sec:.2f} сек)")

        if duration_sec < 0.5:
            return "", duration_sec

        if whisper_model is not None:
            try:
                segments, _ = whisper_model.transcribe(file_path, language="ru")
                text = " ".join([segment.text for segment in segments]).strip()
                print(f"📝 [STT faster-whisper] Распознано: «{text}»")
                if text:
                    return text, duration_sec
            except Exception as exc:
                print(f"⚠️ [STT] Ошибка faster-whisper: {exc}")
                logging.error(f"Local faster-whisper error: {exc}")

        cloud_text = self._cloud_whisper_fallback(file_path)
        print(f"📝 [STT Cloud] Распознано: «{cloud_text}»")
        return cloud_text, duration_sec

    async def text_to_speech_file(self, text: str, output_path: str) -> Optional[str]:
        if not text:
            return None
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(output_path)
            return output_path
        except Exception as exc:
            logging.error(f"Code E21: TTS generation failed ({type(exc).__name__}: {exc})")
            return None

    def text_to_speech(self, text: str, output_path: str = "output.mp3") -> Optional[str]:
        return asyncio.run(self.text_to_speech_file(text, output_path))