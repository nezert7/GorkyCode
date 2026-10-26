import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prompts_and_memory import MemoryManager, build_system_prompt
from voice_service import VoiceService

try:
    from agent_core import run_agent_loop
except ImportError:
    def run_agent_loop(user_query: str, history: list) -> str:
        return f"[Agent Core Stub] Ответ на: {user_query}"

app = FastAPI(title="Voice Assistant Desktop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

memory = MemoryManager()
voice_service = VoiceService()

TEMP_DIR = "temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)


class TextQueryRequest(BaseModel):
    query: str


class TextQueryResponse(BaseModel):
    response: str
    audio_url: str = None


@app.post("/api/chat", response_model=TextQueryResponse)
async def chat_endpoint(data: TextQueryRequest):
    user_text = data.query.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    memory.add_message("user", user_text)
    assistant_reply = run_agent_loop(user_text, memory.get_messages())
    memory.add_message("assistant", assistant_reply)

    audio_filename = "reply.mp3"
    audio_path = os.path.join(TEMP_DIR, audio_filename)
    await voice_service.text_to_speech_file(assistant_reply, audio_path)

    return TextQueryResponse(
        response=assistant_reply,
        audio_url="/api/audio/reply.mp3"
    )


@app.post("/api/voice-chat", response_model=TextQueryResponse)
async def voice_chat_endpoint(file: UploadFile = File(...)):
    temp_input = os.path.join(TEMP_DIR, f"input_{file.filename}")
    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        user_text = voice_service.transcribe_audio_file(temp_input)
    finally:
        if os.path.exists(temp_input):
            os.remove(temp_input)

    if not user_text:
        return TextQueryResponse(response="Не удалось распознать речь.", audio_url=None)

    return await chat_endpoint(TextQueryRequest(query=user_text))


@app.get("/api/audio/{filename}")
async def get_audio(filename: str):
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio not found")


@app.post("/api/clear-history")
async def clear_history():
    memory.clear()
    return {"status": "ok", "message": "History cleared"}


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "static_frontend")

if os.path.exists(FRONTEND_DIR):
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        target = os.path.join(FRONTEND_DIR, full_path)
        if full_path and os.path.exists(target):
            return FileResponse(target)
        index_file = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Frontend not built yet"}
