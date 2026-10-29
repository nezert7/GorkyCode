import os
import shutil
import threading
import time
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import CalendarIntegration, get_intent_label_ru
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

# Очередь сработавших фоновых уведомлений (за 1 час до задачи) для показа в UI
_pending_ui_notifications: List[Dict[str, Any]] = []


def _background_notification_worker():
    """Фоновый поток: каждые 30 сек проверяет задачи, до которых остался 1 час, и шлёт пуш-уведомление."""
    while True:
        try:
            agent = get_shared_agent()
            due_items = agent.db.check_and_trigger_upcoming_notifications()
            for item in due_items:
                kind = get_intent_label_ru(item.get("intent"))
                msg = f"Напоминание за час! {kind}: «{item.get('action')}» в {item.get('parsed_time')}."
                _pending_ui_notifications.append({
                    "id": item.get("id"),
                    "message": msg,
                    "item": item
                })
                print(f"🔔 [УВЕДОМЛЕНИЕ ЗА ЧАС] {msg}")
        except Exception:
            pass
        time.sleep(30)


threading.Thread(target=_background_notification_worker, daemon=True).start()


class TextQueryRequest(BaseModel):
    query: str
    session_id: str = "default"
    audio_duration_sec: float = 2.0


class SessionActionRequest(BaseModel):
    session_id: str = "default"


class TaskUpdateRequest(BaseModel):
    action: Optional[str] = None
    parsed_date: Optional[str] = "__UNSET__"
    parsed_time: Optional[str] = "__UNSET__"
    intent: Optional[str] = None
    status: Optional[str] = None


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
        data=(
            turn_result.get("data")
            or turn_result.get("saved")
            or turn_result.get("deleted")
            or turn_result.get("completed")
            or turn_result.get("updated")
        ),
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
    agent = get_shared_agent()
    res = agent.confirm_pending(session_id=req.session_id)
    res["spoken_response"] = format_spoken_response(res)
    memory.add_message("assistant", res["spoken_response"])
    return await _build_response_with_tts(res)


@app.post("/api/cancel", response_model=TextQueryResponse)
async def cancel_pending_endpoint(req: SessionActionRequest = SessionActionRequest()):
    agent = get_shared_agent()
    res = agent.cancel_pending(session_id=req.session_id)
    res["spoken_response"] = format_spoken_response(res)
    memory.add_message("assistant", res["spoken_response"])
    return await _build_response_with_tts(res)


@app.get("/api/history")
async def get_history_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    intent: Optional[str] = Query(None, description="Task, Reminder или Meeting"),
    status: Optional[str] = Query(None, description="Active или Done"),
    sort_by: str = Query("created_desc", description="created_desc | type | date")
):
    agent = get_shared_agent()
    items = agent.db.get_history(
        limit=limit,
        offset=offset,
        intent_filter=intent,
        status_filter=status,
        sort_by=sort_by
    )
    return {"items": items}


@app.get("/api/tasks")
async def get_tasks_by_period_endpoint(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    intent: Optional[str] = Query(None, description="Task, Reminder или Meeting"),
    sort_by: str = Query("date", description="date или type")
):
    agent = get_shared_agent()
    items = agent.db.get_items_by_period(start_date, end_date or start_date, intent, sort_by=sort_by)
    return {"items": items}


@app.put("/api/tasks/{task_id}")
async def update_task_endpoint(task_id: int, req: TaskUpdateRequest):
    """Редактирование текста, даты, времени, типа или статуса задачи с синхронизацией Календаря."""
    agent = get_shared_agent()
    updated = agent.db.update_item(
        task_id=task_id,
        action=req.action,
        parsed_date=req.parsed_date,
        parsed_time=req.parsed_time,
        intent=req.intent,
        status=req.status
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "updated", "item": updated}


@app.post("/api/tasks/{task_id}/done")
async def mark_task_done_endpoint(task_id: int):
    """Переводит задачу в статус Done."""
    agent = get_shared_agent()
    ok = agent.db.mark_done(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task_id": task_id}


@app.delete("/api/tasks/{task_id}")
async def delete_task_endpoint(task_id: int):
    """Удаляет задачу по ID из SQLite и из системного Календаря."""
    agent = get_shared_agent()
    ok = agent.db.delete_item(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", "task_id": task_id}


@app.get("/api/notifications")
async def pop_upcoming_notifications():
    """Возвращает сработавшие уведомления (за 1 час до задачи) для отображения в UI."""
    items = list(_pending_ui_notifications)
    _pending_ui_notifications.clear()
    return {"notifications": items}


@app.get("/api/calendar.ics")
async def export_ics_calendar():
    agent = get_shared_agent()
    items = agent.db.get_history(limit=200)
    ics_text = CalendarIntegration.export_all_to_ics(items)
    return Response(
        content=ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=vorona_calendar.ics"}
    )


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