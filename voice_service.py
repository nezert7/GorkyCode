import os
import asyncio
import edge_tts
import sounddevice as sd
import numpy as np

try:
    from faster_whisper import WhisperModel
    whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
except Exception:
    whisper_model = None


class VoiceService:
    def __init__(self, voice: str = "ru-RU-SvetlanaNeural"):
        self.voice = voice

    def record_and_transcribe(self, duration_sec: int = 5, sample_rate: int = 16000) -> str:
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
        return " ".join([segment.text for segment in segments]).strip()

    def transcribe_audio_file(self, file_path: str) -> str:
        if whisper_model is None:
            raise RuntimeError("faster-whisper не загружен.")

        segments, _ = whisper_model.transcribe(file_path, language="ru")
        return " ".join([segment.text for segment in segments]).strip()

    async def text_to_speech_file(self, text: str, output_path: str) -> str:
        if not text:
            return ""
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(output_path)
        return output_path

    def text_to_speech(self, text: str, output_path: str = "output.mp3") -> str:
        return asyncio.run(self.text_to_speech_file(text, output_path))

