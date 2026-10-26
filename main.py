import os
import shutil
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prompts_and_memory import MemoryManager
from voice_service import VoiceService
from agent_core import run_agent_turn, get_shared_agent, format_spoken_response

app = FastAPI(title="Ворона — Voice Assistant Desktop API")

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
    session_id: str = "default"
    audio_duration_sec: float = 2.0


class SessionActionRequest(BaseModel):
    session_id: str = "default"


class TextQueryResponse(BaseModel):
    response: str
    audio_url: Optional[str] = None
    ui_status: Optional[str] = None
    operation: Optional[str] = None
    requires_confirmation: bool = False
    data: Optional[Dict[str, Any]] = None
    items: Optional[List[Dict[str, Any]]] = None
    error_code: Optional[str] = None
    hint: Optional[str] = None


async def _build_response_with_tts(turn_result: Dict[str, Any]) -> TextQueryResponse:
    spoken_text = turn_result.get("spoken_response") or format_spoken_response(turn_result)
    audio_filename = "reply.mp3"
    audio_path = os.path.join(TEMP_DIR, audio_filename)

    saved_audio = await voice_service.text_to_speech_file(spoken_text, audio_path)
    audio_url = f"/api/audio/{audio_filename}" if saved_audio else None

    return TextQueryResponse(
        response=spoken_text,
        audio_url=audio_url,
        ui_status=turn_result.get("ui_status"),
        operation=turn_result.get("operation"),
        requires_confirmation=turn_result.get("requires_confirmation", False),
        data=turn_result.get("data") or turn_result.get("saved"),
        items=turn_result.get("items"),
        error_code=turn_result.get("error_code"),
        hint=turn_result.get("hint")
    )


@app.post("/api/chat", response_model=TextQueryResponse)
async def chat_endpoint(data: TextQueryRequest):
    user_text = data.query.strip()

    if user_text:
        memory.add_message("user", user_text)

    turn_result = run_agent_turn(
        user_query=user_text,
        history=memory.get_messages(),
        session_id=data.session_id,
        audio_duration_sec=data.audio_duration_sec
    )

    assistant_reply = turn_result["spoken_response"]
    memory.add_message("assistant", assistant_reply)

    return await _build_response_with_tts(turn_result)


@app.post("/api/voice-chat", response_model=TextQueryResponse)
async def voice_chat_endpoint(file: UploadFile = File(...)):
    temp_input = os.path.join(TEMP_DIR, f"input_{file.filename}")
    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        user_text, duration_sec = voice_service.transcribe_audio_file(temp_input)
    finally:
        if os.path.exists(temp_input):
            os.remove(temp_input)

    return await chat_endpoint(
        TextQueryRequest(
            query=user_text,
            session_id="default",
            audio_duration_sec=duration_sec
        )
    )


@app.post("/api/confirm", response_model=TextQueryResponse)
async def confirm_pending_endpoint(req: SessionActionRequest = SessionActionRequest()):
    """Эндпоинт для кнопки UI «Верно»."""
    agent = get_shared_agent()
    res = agent.confirm_pending(session_id=req.session_id)
    res["spoken_response"] = format_spoken_response(res)
    memory.add_message("assistant", res["spoken_response"])
    return await _build_response_with_tts(res)


@app.post("/api/cancel", response_model=TextQueryResponse)
async def cancel_pending_endpoint(req: SessionActionRequest = SessionActionRequest()):
    """Эндпоинт для кнопки UI «Неверно»."""
    agent = get_shared_agent()
    res = agent.cancel_pending(session_id=req.session_id)
    res["spoken_response"] = format_spoken_response(res)
    memory.add_message("assistant", res["spoken_response"])
    return await _build_response_with_tts(res)


@app.get("/api/history")
async def get_history_endpoint(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Возвращает историю сохранённых задач и встреч из SQLite (новые сверху)."""
    agent = get_shared_agent()
    return {"items": agent.db.get_history(limit=limit, offset=offset)}


@app.get("/api/tasks")
async def get_tasks_by_period_endpoint(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    intent: Optional[str] = Query(None, description="Task или Meeting")
):
    """Возвращает список задач/встреч за выбранный период."""
    agent = get_shared_agent()
    items = agent.db.get_items_by_period(start_date, end_date or start_date, intent)
    return {"items": items}


@app.post("/api/tasks/{task_id}/done")
async def mark_task_done_endpoint(task_id: int):
    """Переводит задачу в статус Done."""
    agent = get_shared_agent()
    ok = agent.db.mark_done(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task_id": task_id}


@app.get("/api/audio/{filename}")
async def get_audio(filename: str):
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio not found")


@app.post("/api/clear-history")
async def clear_history():
    memory.clear()
    get_shared_agent().cancel_pending("default")
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
