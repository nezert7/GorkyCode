import os
import wave
import time
import logging
import asyncio
import edge_tts
import sounddevice as sd
import numpy as np
from typing import Tuple, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

# === ФИКС НЕСОВМЕСТИМОСТИ PYAV И FASTER-WHISPER (metadata_errors) ===
try:
    import av
    _orig_av_open = av.open

    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)

    av.open = _safe_av_open
except Exception:
    pass

# === 1. ЗАГРУЗКА ЛОКАЛЬНОЙ МОДЕЛИ СБЕРА GIGAAM V3 НА CPU (БЕЗ ОШИБОК COREML) ===
gigaam_model = None
try:
    import onnx_asr
    # Принудительно используем CPUExecutionProvider, чтобы избежать сбоя CoreMLExecutionProvider на macOS
    gigaam_model = onnx_asr.load_model(
        "gigaam-v3-e2e-ctc",
        providers=["CPUExecutionProvider"]
    )
    print("🚀 [STT] Локальная модель Сбера GigaAM v3 (ONNX CPU) успешно загружена!")
except Exception as e:
    try:
        import onnx_asr
        gigaam_model = onnx_asr.load_model(
            "gigaam-v2-ctc",
            providers=["CPUExecutionProvider"]
        )
        print("🚀 [STT] Локальная модель Сбера GigaAM v2 (ONNX CPU) успешно загружена!")
    except Exception as sub_e:
        gigaam_model = None
        print(f"⚠️ [STT] Не удалось загрузить GigaAM ({e} / {sub_e})")

# === 2. ЗАГРУЗКА FASTER-WHISPER (РЕЗЕРВ И ДЕКОДЕР АУДИО) ===
whisper_model = None
try:
    from faster_whisper import WhisperModel
    import faster_whisper.audio
    if hasattr(faster_whisper.audio, "av"):
        faster_whisper.audio.av.open = _safe_av_open

    model_size = os.getenv("WHISPER_MODEL_SIZE") or "base"
    whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4)
    print(f"✅ [STT] Резервная модель faster-whisper ({model_size}) готова.")
except Exception as e:
    print(f"⚠️ [STT] faster-whisper не загружен ({e}).")


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
            return max(0.6, size_bytes / 16000.0) if size_bytes > 1200 else 0.2
        except Exception:
            return 2.0

    @staticmethod
    def _decode_audio_to_float32_16k(file_path: str) -> Optional[np.ndarray]:
        """Декодирует любой аудиофайл (.webm, .ogg, .wav, .mp4) в 1D массив float32 (16 кГц) в ОЗУ."""
        # Способ 1: через встроенный декодер faster_whisper.audio
        try:
            import faster_whisper.audio
            waveform = faster_whisper.audio.decode_audio(file_path, sampling_rate=16000)
            if waveform is not None and len(waveform) > 0:
                return np.asarray(waveform, dtype=np.float32).flatten()
        except Exception:
            pass

        # Способ 2: напрямую через PyAV
        try:
            import av
            container = av.open(file_path)
            resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
            chunks = []
            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    chunks.append(resampled.to_ndarray().flatten())
            container.close()
            if chunks:
                return np.concatenate(chunks).astype(np.float32)
        except Exception:
            pass

        return None

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
        print(f"[*] Запись голоса ({duration_sec} сек)...")
        audio_data = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32"
        )
        sd.wait()
        waveform = audio_data.flatten()

        if gigaam_model is not None:
            res = gigaam_model.recognize(waveform, sample_rate=sample_rate)
            text = (" ".join(res) if isinstance(res, list) else str(res or "")).strip()
            return text, float(duration_sec)

        if whisper_model is None:
            raise RuntimeError("Модели STT не загружены.")
        segments, _ = whisper_model.transcribe(waveform, language="ru", beam_size=1)
        text = " ".join([segment.text for segment in segments]).strip()
        return text, float(duration_sec)

    def transcribe_audio_file(self, file_path: str) -> Tuple[str, float]:
        duration_sec = self.get_audio_duration(file_path)
        t0 = time.time()
        print(f"🎙 [STT] Получен аудиофайл: {file_path} (~{duration_sec:.2f} сек)")

        if duration_sec < 0.5:
            return "", duration_sec

        # 1. Основной движок: Sber GigaAM v3 (работает в ОЗУ на CPU без CoreML-ошибок)
        if gigaam_model is not None:
            try:
                waveform = self._decode_audio_to_float32_16k(file_path)
                if waveform is not None and waveform.size > 0:
                    giga_text = gigaam_model.recognize(waveform, sample_rate=16000)
                    if isinstance(giga_text, list):
                        giga_text = " ".join(str(x) for x in giga_text)
                    giga_text = (giga_text or "").strip()
                    if giga_text:
                        print(f"📝 [STT Sber GigaAM v3] ({time.time() - t0:.2f} сек) Распознано: «{giga_text}»")
                        return giga_text, duration_sec
            except Exception as exc:
                print(f"⚠️ [STT GigaAM] Ошибка ({exc}), переключение на faster-whisper.")

        # 2. Резервный локальный движок: faster-whisper
        if whisper_model is not None:
            try:
                segments, _ = whisper_model.transcribe(
                    file_path,
                    language="ru",
                    beam_size=2,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=300),
                    condition_on_previous_text=False
                )
                text = " ".join([segment.text for segment in segments]).strip()
                print(f"📝 [STT faster-whisper] ({time.time() - t0:.2f} сек) Распознано: «{text}»")
                if text:
                    return text, duration_sec
            except Exception as exc:
                print(f"⚠️ [STT] Ошибка faster-whisper: {exc}")
                logging.error(f"Local faster-whisper error: {exc}")

        # 3. Облачный резерв (если задан GROQ_API_KEY)
        cloud_text = self._cloud_whisper_fallback(file_path)
        if cloud_text:
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
