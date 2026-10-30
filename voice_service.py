import os
import io
import wave
import time
from collections import OrderedDict
import edge_tts
import numpy as np
from typing import Tuple, Optional
from dotenv import load_dotenv

load_dotenv(override=True)

# Отключаем предупреждение и ошибку прав доступа к symlink на Windows при скачивании GigaAM
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("ORT_TENSORRT_UNAVAILABLE", "1")

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

# Загрузка локальной модели Сбера GigaAM v3 / v2 (ONNX CPU)
gigaam_model = None
for _model_name in ("gigaam-v3-e2e-ctc", "gigaam-v2-ctc"):
    try:
        import onnx_asr
        gigaam_model = onnx_asr.load_model(_model_name, providers=["CPUExecutionProvider"])
        print(f"🚀 [STT] Локальная модель Сбера {_model_name} (ONNX CPU) успешно загружена!")
        break
    except Exception:
        continue

if gigaam_model is None:
    print("⚠️ [STT] Не удалось загрузить локальную модель GigaAM.")


class VoiceService:
    """
    Голосовой сервис полностью в оперативной памяти (ОЗУ):
    - STT: декодирование байтов через PyAV в ОЗУ + обрезка тишины -> Sber GigaAM (ONNX CPU).
    - TTS: генерация MP3-потока через edge-tts напрямую в память с LRU-кэшем фраз.
    """

    MAX_AUDIO_CACHE = 20
    MAX_PHRASE_CACHE = 64

    def __init__(self, voice: str = "ru-RU-SvetlanaNeural"):
        self.voice = voice
        self.memory_audio: OrderedDict[str, bytes] = OrderedDict()
        self._tts_phrase_cache: OrderedDict[str, bytes] = OrderedDict()

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
    def _trim_silence(waveform: np.ndarray, threshold: float = 0.008, pad_samples: int = 1600) -> np.ndarray:
        """Обрезает тишину по краям записи, ускоряя распознавание на 30-40%."""
        if waveform.size <= pad_samples * 2:
            return waveform
        mask = np.abs(waveform) > threshold
        if not np.any(mask):
            return np.array([], dtype=np.float32)
        indices = np.flatnonzero(mask)
        start = max(0, int(indices[0]) - pad_samples)
        end = min(waveform.size, int(indices[-1]) + pad_samples)
        return waveform[start:end]

    @classmethod
    def _decode_bytes_to_float32_16k(cls, audio_bytes: bytes) -> Optional[np.ndarray]:
        """Декодирует аудио из байтов в ОЗУ (.webm, .ogg, .wav, .mp4) в 1D массив float32 (16 кГц)."""
        if not audio_bytes:
            return None

        if av is not None:
            try:
                with av.open(io.BytesIO(audio_bytes)) as container:
                    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
                    chunks = [
                        resampled.to_ndarray().ravel()
                        for frame in container.decode(audio=0)
                        for resampled in resampler.resample(frame)
                    ]
                if chunks:
                    waveform = np.concatenate(chunks).astype(np.float32, copy=False)
                    return cls._trim_silence(waveform)
            except Exception:
                pass

        if audio_bytes.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) * (1.0 / 32768.0)
                    if wf.getnchannels() > 1:
                        samples = samples[::wf.getnchannels()]
                    return cls._trim_silence(samples)
            except Exception:
                pass

        return None

    def transcribe_audio_bytes(self, audio_bytes: bytes) -> Tuple[str, float]:
        """Распознаёт речь через GigaAM напрямую из байтов в ОЗУ без создания файлов на диске."""
        duration_sec = self.estimate_duration_from_bytes(audio_bytes)
        t0 = time.time()

        if duration_sec < 0.45 or gigaam_model is None:
            return "", duration_sec

        try:
            waveform = self._decode_bytes_to_float32_16k(audio_bytes)
            if waveform is not None and waveform.size > 0:
                real_duration = float(waveform.size) / 16000.0
                if real_duration < 0.25:
                    return "", real_duration

                giga_text = gigaam_model.recognize(waveform, sample_rate=16000)
                if isinstance(giga_text, list):
                    giga_text = " ".join(str(x) for x in giga_text)
                giga_text = (giga_text or "").strip()
                print(f"📝 [STT GigaAM] ({time.time() - t0:.2f} сек) Распознано: «{giga_text}»")
                return giga_text, max(0.6, real_duration)
        except Exception as exc:
            print(f"⚠️ [STT GigaAM] Ошибка распознавания: {exc}")

        return "", duration_sec

    async def text_to_speech_bytes(self, text: str) -> Optional[bytes]:
        """Генерирует MP3-байты через edge-tts напрямую в ОЗУ с кэшированием фраз."""
        clean_text = (text or "").strip()
        if not clean_text:
            return None

        if clean_text in self._tts_phrase_cache:
            self._tts_phrase_cache.move_to_end(clean_text)
            return self._tts_phrase_cache[clean_text]

        try:
            communicate = edge_tts.Communicate(clean_text, self.voice)
            buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buffer.extend(chunk["data"])
            if not buffer:
                return None

            mp3_bytes = bytes(buffer)
            self._tts_phrase_cache[clean_text] = mp3_bytes
            if len(self._tts_phrase_cache) > self.MAX_PHRASE_CACHE:
                self._tts_phrase_cache.popitem(last=False)
            return mp3_bytes
        except Exception:
            return None

    async def text_to_speech_in_memory(self, text: str, audio_key: str = "reply.mp3") -> Optional[str]:
        """Сохраняет озвучку в кольцевой словарь ОЗУ (self.memory_audio)."""
        mp3_bytes = await self.text_to_speech_bytes(text)
        if not mp3_bytes:
            return None
        key = os.path.basename(audio_key) if audio_key else "reply.mp3"
        self.memory_audio[key] = mp3_bytes
        self.memory_audio.move_to_end(key)
        while len(self.memory_audio) > self.MAX_AUDIO_CACHE:
            self.memory_audio.popitem(last=False)
        return key

    def get_cached_audio(self, filename: str) -> Optional[bytes]:
        return self.memory_audio.get(os.path.basename(filename))
