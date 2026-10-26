import os
import pytest
from fastapi.testclient import TestClient

from prompts_and_memory import MemoryManager, build_system_prompt
from voice_service import VoiceService
from main import app


def test_system_prompt():
    prompt = build_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 20
    assert "Текущее локальное время и дата:" in prompt


def test_memory_manager():
    memory = MemoryManager(max_history=3)
    memory.clear()
    memory.add_message("user", "Привет!")
    memory.add_message("assistant", "Здравствуйте!")

    messages = memory.get_messages()
    assert len(messages) == 2
    assert messages[0]["content"] == "Привет!"

    memory.clear()
    assert len(memory.get_messages()) == 0


@pytest.mark.asyncio
async def test_edge_tts_file():
    service = VoiceService()
    test_audio = "test_check.mp3"
    try:
        path = await service.text_to_speech_file("Привет, проверка звука", test_audio)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 500
    finally:
        if os.path.exists(test_audio):
            os.remove(test_audio)


client = TestClient(app)


def test_api_chat():
    res = client.post("/api/chat", json={"query": "Привет, ассистент!"})
    assert res.status_code == 200
    data = res.json()
    assert "response" in data
    assert "audio_url" in data


def test_api_clear():
    res = client.post("/api/clear-history")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
