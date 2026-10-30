import os
import time
import asyncio
import threading
import sys
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import (
    hash_password,
    verify_password,
    validate_password_strength,
    create_access_token,
    get_current_user,
)
from database import CalendarIntegration, get_intent_label_ru
from prompts_and_memory import MemoryManager
from voice_service import VoiceService
from agent_core import run_agent_turn, get_shared_agent, format_spoken_response

app = FastAPI(title="Ворона — In-Memory Voice Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

voice_service = VoiceService()

_user_memories: Dict[int, MemoryManager] = {}
_pending_ui_notifications: Dict[int, List[Dict[str, Any]]] = {}


def get_user_memory(user_id: int) -> MemoryManager:
    if user_id not in _user_memories:
        _user_memories[user_id] = MemoryManager()
    return _user_memories[user_id]


def _background_notification_worker():
    """каждые 30 сек проверяет задачи за 1 час до начала"""
    while True:
        try:
            agent = get_shared_agent()
            due_items = agent.db.check_and_trigger_upcoming_notifications()
            for item in due_items:
                uid = int(item.get("user_id") or 1)
                kind = get_intent_label_ru(item.get("intent"))
                msg = f"Напоминание за час! {kind}: «{item.get('action')}» в {item.get('parsed_time')}."
                _pending_ui_notifications.setdefault(uid, []).append({
                    "id": item.get("id"),
                    "message": msg,
                    "item": item
                })
        except Exception:
            pass
        time.sleep(30)


threading.Thread(target=_background_notification_worker, daemon=True).start()


# МОДЕЛИ ДАННЫХ

class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: Dict[str, Any]


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


# АВТОРИЗАЦИЯ

@app.post("/api/auth/register", response_model=AuthResponse)
async def register_endpoint(req: AuthRequest):
    username = req.username.strip()
    password = req.password

    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Логин должен содержать минимум 2 символа")

    pwd_error = validate_password_strength(password, username)
    if pwd_error:
        raise HTTPException(status_code=400, detail=pwd_error)

    agent = get_shared_agent()
    if agent.db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует")

    created_user = agent.db.create_user(username, hash_password(password))
    if not created_user:
        raise HTTPException(status_code=500, detail="Не удалось создать пользователя")

    token = create_access_token(created_user["id"], created_user["username"])
    return AuthResponse(token=token, user={"id": created_user["id"], "username": created_user["username"]})


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_endpoint(req: AuthRequest):
    username = req.username.strip()
    password = req.password

    agent = get_shared_agent()
    user_row = agent.db.get_user_by_username(username)
    if not user_row or not verify_password(password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    token = create_access_token(user_row["id"], user_row["username"])
    return AuthResponse(token=token, user={"id": user_row["id"], "username": user_row["username"]})


@app.get("/api/auth/me")
async def me_endpoint(current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"user": current_user}


#  IN-MEMORY ГОЛОС И ЧАТ

async def _build_response_with_tts(turn_result: Dict[str, Any], user_id: int) -> TextQueryResponse:
    spoken_text = turn_result.get("spoken_response") or format_spoken_response(turn_result)
    audio_key = f"reply_u{user_id}.mp3"

    saved_key = await voice_service.text_to_speech_in_memory(spoken_text, audio_key)
    audio_url = f"/api/audio/{saved_key}" if saved_key else None

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
async def chat_endpoint(
    data: TextQueryRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    user_text = data.query.strip()
    mem = get_user_memory(user_id)

    if user_text:
        mem.add_message("user", user_text)

    turn_result = await asyncio.to_thread(
        run_agent_turn,
        user_query=user_text,
        history=mem.get_messages(),
        session_id=data.session_id,
        audio_duration_sec=data.audio_duration_sec,
        user_id=user_id
    )

    assistant_reply = turn_result["spoken_response"]
    mem.add_message("assistant", assistant_reply)

    return await _build_response_with_tts(turn_result, user_id=user_id)


@app.post("/api/voice-chat", response_model=TextQueryResponse)
async def voice_chat_endpoint(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    audio_bytes = await file.read()

    user_text, duration_sec = await asyncio.to_thread(
        voice_service.transcribe_audio_bytes,
        audio_bytes
    )

    return await chat_endpoint(
        TextQueryRequest(
            query=user_text,
            session_id="default",
            audio_duration_sec=duration_sec
        ),
        current_user=current_user
    )


@app.post("/api/confirm", response_model=TextQueryResponse)
async def confirm_pending_endpoint(
    req: SessionActionRequest = SessionActionRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    agent = get_shared_agent()
    res = await asyncio.to_thread(
        agent.confirm_pending,
        session_id=req.session_id,
        user_id=user_id
    )
    res["spoken_response"] = format_spoken_response(res)
    get_user_memory(user_id).add_message("assistant", res["spoken_response"])
    return await _build_response_with_tts(res, user_id=user_id)


@app.post("/api/cancel", response_model=TextQueryResponse)
async def cancel_pending_endpoint(
    req: SessionActionRequest = SessionActionRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    agent = get_shared_agent()
    res = await asyncio.to_thread(
        agent.cancel_pending,
        session_id=req.session_id,
        user_id=user_id
    )
    res["spoken_response"] = format_spoken_response(res)
    get_user_memory(user_id).add_message("assistant", res["spoken_response"])
    return await _build_response_with_tts(res, user_id=user_id)


@app.get("/api/audio/{filename}")
async def get_audio_from_ram(filename: str):
    mp3_bytes = voice_service.get_cached_audio(filename)
    if mp3_bytes:
        return Response(
            content=mp3_bytes,
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-store"}
        )
    raise HTTPException(status_code=404, detail="Audio not found in memory")


#  ЗАДАЧИ, ИСТОРИЯ И КАЛЕНДАРЬ

@app.get("/api/history")
async def get_history_endpoint(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    intent: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort_by: str = Query("created_desc"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    items = get_shared_agent().db.get_history(
        limit=limit,
        offset=offset,
        intent_filter=intent,
        status_filter=status,
        sort_by=sort_by,
        user_id=user_id
    )
    return {"items": items}


@app.get("/api/tasks")
async def get_tasks_by_period_endpoint(
    start_date: str = Query(...),
    end_date: Optional[str] = Query(None),
    intent: Optional[str] = Query(None),
    sort_by: str = Query("date"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    items = get_shared_agent().db.get_items_by_period(
        start_date,
        end_date or start_date,
        intent,
        sort_by=sort_by,
        user_id=user_id
    )
    return {"items": items}


@app.put("/api/tasks/{task_id}")
async def update_task_endpoint(
    task_id: int,
    req: TaskUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    updated = get_shared_agent().db.update_item(
        task_id=task_id,
        action=req.action,
        parsed_date=req.parsed_date,
        parsed_time=req.parsed_time,
        intent=req.intent,
        status=req.status,
        user_id=user_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "updated", "item": updated}


@app.post("/api/tasks/{task_id}/done")
async def mark_task_done_endpoint(
    task_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    ok = get_shared_agent().db.mark_done(task_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task_id": task_id}


@app.delete("/api/tasks/{task_id}")
async def delete_task_endpoint(
    task_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["id"])
    ok = get_shared_agent().db.delete_item(task_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", "task_id": task_id}


@app.get("/api/notifications")
async def pop_upcoming_notifications(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = int(current_user["id"])
    user_queue = _pending_ui_notifications.get(user_id, [])
    items = list(user_queue)
    user_queue.clear()
    return {"notifications": items}


@app.get("/api/calendar.ics")
async def export_ics_calendar(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = int(current_user["id"])
    items = get_shared_agent().db.get_history(limit=500, user_id=user_id)
    ics_text = CalendarIntegration.export_all_to_ics(items)
    return Response(
        content=ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=vorona_{current_user['username']}.ics"}
    )


@app.post("/api/clear-history")
async def clear_history(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = int(current_user["id"])
    get_user_memory(user_id).clear()
    get_shared_agent().cancel_pending("default", user_id=user_id)
    return {"status": "ok", "message": "History cleared"}

BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "static_frontend")

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
