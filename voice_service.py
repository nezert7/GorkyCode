import os
import io
import wave
import time
import asyncio
import edge_tts
import sounddevice as sd
import numpy as np
from typing import Tuple, Optional, Dict
from dotenv import load_dotenv

load_dotenv(override=True)

# Патч совместимости PyAV
try:
    import av
    _orig_av_open = av.open

    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)

    av.open = _safe_av_open
except Exception:
    av = None

# Загрузка локальной модели Сбера GigaAM v3 (ONNX CPU)
gigaam_model = None
try:
    import onnx_asr
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


class VoiceService:
    """
    Голосовой сервис полностью в оперативной памяти (ОЗУ):
    - STT: декодирование байтов через PyAV в ОЗУ -> распознавание через Sber GigaAM v3 (ONNX CPU).
    - TTS: генерация MP3-потока через edge-tts напрямую в память без записи файлов на диск.
    """

    def __init__(self, voice: str = "ru-RU-SvetlanaNeural"):
        self.voice = voice
        self.memory_audio: Dict[str, bytes] = {}

    @staticmethod
    def estimate_duration_from_bytes(audio_bytes: bytes) -> float:
        if not audio_bytes or len(audio_bytes) < 800:
            return 0.2
        if audio_bytes.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    rate = wf.getframerate()
                    if rate > 0:
                        return wf.getnframes() / float(rate)
            except Exception:
                pass
        return max(0.8, len(audio_bytes) / 16000.0)

    @staticmethod
    def _decode_bytes_to_float32_16k(audio_bytes: bytes) -> Optional[np.ndarray]:
        """Декодирует аудио из байтов в ОЗУ (.webm, .ogg, .wav, .mp4) в 1D массив float32 (16 кГц)."""
        if not audio_bytes:
            return None

        # 1. Декодирование через PyAV напрямую из BytesIO в ОЗУ
        if av is not None:
            try:
                container = av.open(io.BytesIO(audio_bytes))
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

        # 2. Резерв для чистого WAV (16-bit PCM)
        if audio_bytes.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                    if wf.getnchannels() > 1:
                        samples = samples[::wf.getnchannels()]
                    return samples
            except Exception:
                pass

        return None

    def record_and_transcribe(self, duration_sec: int = 5, sample_rate: int = 16000) -> Tuple[str, float]:
        if gigaam_model is None:
            raise RuntimeError("Модель GigaAM не загружена.")

        print(f"[*] Запись голоса ({duration_sec} сек)...")
        audio_data = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32"
        )
        sd.wait()
        waveform = audio_data.flatten()

        res = gigaam_model.recognize(waveform, sample_rate=sample_rate)
        text = (" ".join(str(x) for x in res) if isinstance(res, list) else str(res or "")).strip()
        return text, float(duration_sec)

    def transcribe_audio_bytes(self, audio_bytes: bytes, filename: str = "record.webm") -> Tuple[str, float]:
        """Распознаёт речь через GigaAM v3 напрямую из байтов в ОЗУ без создания файлов на диске."""
        duration_sec = self.estimate_duration_from_bytes(audio_bytes)
        t0 = time.time()

        if duration_sec < 0.5 or gigaam_model is None:
            return "", duration_sec

        try:
            waveform = self._decode_bytes_to_float32_16k(audio_bytes)
            if waveform is not None and waveform.size > 0:
                real_duration = float(waveform.size) / 16000.0
                if real_duration < 0.4:
                    return "", real_duration

                giga_text = gigaam_model.recognize(waveform, sample_rate=16000)
                if isinstance(giga_text, list):
                    giga_text = " ".join(str(x) for x in giga_text)
                giga_text = (giga_text or "").strip()
                print(f"📝 [STT GigaAM v3] ({time.time() - t0:.2f} сек) Распознано: «{giga_text}»")
                return giga_text, real_duration
        except Exception as exc:
            print(f"⚠️ [STT GigaAM] Ошибка распознавания: {exc}")

        return "", duration_sec

    def transcribe_audio_file(self, file_path: str) -> Tuple[str, float]:
        """Совместимость: читает файл в память и сразу удаляет его с диска."""
        if not file_path or not os.path.exists(file_path):
            return "", 0.0
        try:
            with open(file_path, "rb") as f:
                audio_bytes = f.read()
        finally:
            try:
                os.remove(file_path)
            except OSError:
                pass
        return self.transcribe_audio_bytes(audio_bytes, os.path.basename(file_path))

    async def text_to_speech_bytes(self, text: str) -> Optional[bytes]:
        """Генерирует MP3-байты через edge-tts напрямую в ОЗУ."""
        if not text or not text.strip():
            return None
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buffer.extend(chunk["data"])
            return bytes(buffer) if buffer else None
        except Exception:
            return None

    async def text_to_speech_file(self, text: str, output_path: str = "reply.mp3") -> Optional[str]:
        """Сохраняет озвучку в словарь ОЗУ (self.memory_audio) без создания mp3-файлов на диске."""
        mp3_bytes = await self.text_to_speech_bytes(text)
        if not mp3_bytes:
            return None
        key = os.path.basename(output_path) if output_path else "reply.mp3"
        self.memory_audio[key] = mp3_bytes
        return key

    def get_cached_audio(self, filename: str) -> Optional[bytes]:
        return self.memory_audio.get(os.path.basename(filename))

    def text_to_speech(self, text: str, output_path: str = "output.mp3") -> Optional[str]:
        return asyncio.run(self.text_to_speech_file(text, output_path))
