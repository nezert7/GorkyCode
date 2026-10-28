import os
import sys
import sqlite3
import re
import hashlib
import subprocess
import numpy as np
import pymorphy3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Инициализируем морфологический анализатор русского языка (загружается 1 раз в ОЗУ)
morph = pymorphy3.MorphAnalyzer()

VECTOR_DIM = 512  # Размерность вектора NumPy для семантического поиска


class TextVectorizer:
    """
    Превращает любой русский текст в нормализованные леммы и 512-мерный вектор NumPy (float32).
    Устойчив к падежам, однокоренным словам и опечаткам распознавания речи.
    """

    @staticmethod
    def extract_lemmas(text: str) -> str:
        words = re.findall(r"[а-яёa-z0-9]+", text.lower())
        lemmas = [morph.parse(w)[0].normal_form for w in words if len(w) > 1]
        return " ".join(lemmas)

    @classmethod
    def text_to_vector(cls, text: str) -> np.ndarray:
        vec = np.zeros(VECTOR_DIM, dtype=np.float32)
        clean_text = re.sub(r"[^а-яёa-z0-9\s]", "", text.lower()).strip()
        if not clean_text:
            return vec

        lemmas_str = cls.extract_lemmas(clean_text)
        combined = f" {clean_text} {lemmas_str} "

        for lemma in lemmas_str.split():
            idx = int(hashlib.md5(lemma.encode("utf-8")).hexdigest(), 16) % VECTOR_DIM
            vec[idx] += 2.0

        for i in range(len(combined) - 2):
            trigram = combined[i : i + 3]
            idx = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16) % VECTOR_DIM
            vec[idx] += 1.0

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


class CalendarIntegration:
    """
    Интеграция с реальным календарём:
    1. На macOS добавляет события напрямую в системное приложение Apple «Календарь» через AppleScript.
    2. На всех ОС обновляет стандартный файл vorona_calendar.ics (RFC 5545 iCalendar).
    """

    ICS_FILE_PATH = "vorona_calendar.ics"

    @classmethod
    def sync_event_to_os_calendar(cls, item: Dict[str, Any]) -> bool:
        """Добавляет событие в нативный календарь macOS (Apple Calendar), если указана дата."""
        parsed_date = item.get("parsed_date")
        if not parsed_date:
            return False

        parsed_time = item.get("parsed_time") or "09:00"
        title = (item.get("action") or "Задача Ворона").replace('"', '\\"')
        intent_label = "Встреча" if item.get("intent") == "Meeting" else "Задача"
        description = f"{intent_label} из голосового ассистента Ворона: {title}"

        if sys.platform == "darwin":
            try:
                dt = datetime.strptime(f"{parsed_date} {parsed_time}", "%Y-%m-%d %H:%M")
                applescript = f'''
                tell application "Calendar"
                    if (count of calendars) > 0 then
                        tell calendar 1
                            set startDate to current date
                            set year of startDate to {dt.year}
                            set month of startDate to {dt.month}
                            set day of startDate to {dt.day}
                            set hours of startDate to {dt.hour}
                            set minutes of startDate to {dt.minute}
                            set seconds of startDate to 0
                            set endDate to startDate + (60 * minutes)
                            make new event at end with properties {{summary:"{title}", start date:startDate, end date:endDate, description:"{description}"}}
                        end tell
                    end if
                end tell
                '''
                subprocess.Popen(
                    ["osascript", "-e", applescript],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
            except Exception:
                return False
        return False

    @classmethod
    def export_all_to_ics(cls, items: List[Dict[str, Any]]) -> str:
        """Генерирует содержимое .ics файла для всех активных задач с датой."""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Vorona Voice Assistant//RU",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH"
        ]
        for it in items:
            d_str = it.get("parsed_date")
            if not d_str:
                continue
            t_str = it.get("parsed_time") or "09:00"
            try:
                start_dt = datetime.strptime(f"{d_str} {t_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            end_dt = start_dt + timedelta(hours=1)
            uid = f"vorona-task-{it.get('id', 0)}@vorona.local"
            summary = (it.get("action") or "Задача").replace("\n", " ")
            kind = "Встреча" if it.get("intent") == "Meeting" else "Задача"

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:[{kind}] {summary}",
                f"DESCRIPTION:Создано голосовым ассистентом Ворона ({it.get('raw_text', '')})",
                f"STATUS:{'CONFIRMED' if it.get('status') == 'Active' else 'COMPLETED'}",
                "END:VEVENT"
            ])
        lines.append("END:VCALENDAR")
        ics_content = "\r\n".join(lines)
        try:
            with open(cls.ICS_FILE_PATH, "w", encoding="utf-8") as f:
                f.write(ics_content)
        except Exception:
            pass
        return ics_content


class DatabaseManager:
    """
    Слой хранения данных SQLite + Поиск на NumPy + Управление статусами и Календарём.
    """

    def __init__(self, db_path: str = "events.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent       TEXT    NOT NULL CHECK (intent IN ('Task','Meeting')),
                    raw_text     TEXT    NOT NULL,
                    action       TEXT    NOT NULL,
                    parsed_date  TEXT    CHECK (parsed_date IS NULL OR parsed_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
                    parsed_time  TEXT    CHECK (parsed_time IS NULL OR parsed_time GLOB '[0-2][0-9]:[0-5][0-9]'),
                    date_in_past INTEGER NOT NULL DEFAULT 0 CHECK (date_in_past IN (0,1)),
                    status       TEXT    NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Done')),
                    parse_method TEXT    NOT NULL CHECK (parse_method IN ('llm','regex')),
                    created_at   TEXT    NOT NULL,
                    lemmas       TEXT,
                    embedding    BLOB
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks (parsed_date);")
            conn.commit()

    def save_confirmed_item(
        self,
        intent: str,
        raw_text: str,
        action: str,
        parsed_date: Optional[str],
        parsed_time: Optional[str],
        date_in_past: int = 0,
        parse_method: str = "llm",
        now_override: Optional[datetime] = None
    ) -> Dict[str, Any]:
        now_dt = now_override or datetime.now()
        created_at = now_dt.strftime("%Y-%m-%dT%H:%M:%S")

        search_target = f"{action} {raw_text}"
        lemmas = TextVectorizer.extract_lemmas(search_target)
        vector_bytes = TextVectorizer.text_to_vector(search_target).tobytes()

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (
                    intent, raw_text, action, parsed_date, parsed_time,
                    date_in_past, status, parse_method, created_at, lemmas, embedding
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?, ?)
            """, (
                intent, raw_text, action, parsed_date, parsed_time,
                date_in_past, parse_method, created_at, lemmas, vector_bytes
            ))
            conn.commit()
            new_id = cursor.lastrowid

        saved = {
            "id": new_id,
            "intent": intent,
            "raw_text": raw_text,
            "action": action,
            "parsed_date": parsed_date,
            "parsed_time": parsed_time,
            "date_in_past": date_in_past,
            "status": "Active",
            "parse_method": parse_method,
            "created_at": created_at
        }

        # Автоматическая синхронизация с системным календарём (если это рабочий файл БД, а не in-memory тест)
        if self.db_path != ":memory:" and not self.db_path.startswith("test"):
            CalendarIntegration.sync_event_to_os_calendar(saved)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200))

        return saved

    def check_meeting_conflict(self, parsed_date: str, parsed_time: str) -> List[Dict[str, Any]]:
        if not parsed_date or not parsed_time:
            return []
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, intent, action, parsed_date, parsed_time
                FROM tasks
                WHERE parsed_date = ? AND parsed_time = ? AND status = 'Active'
            """, (parsed_date, parsed_time)).fetchall()
            return [dict(r) for r in rows]

    def get_items_by_period(
        self,
        start_date: str,
        end_date: str,
        intent_filter: Optional[str] = None,
        sort_by: str = "date"
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT id, intent, raw_text, action, parsed_date, parsed_time,
                   date_in_past, status, parse_method, created_at
            FROM tasks
            WHERE parsed_date >= ? AND parsed_date <= ? AND status = 'Active'
        """
        params: List[Any] = [start_date, end_date]

        if intent_filter in ("Task", "Meeting"):
            query += " AND intent = ?"
            params.append(intent_filter)

        if sort_by == "type":
            query += " ORDER BY intent ASC, parsed_date ASC, COALESCE(parsed_time, '23:59') ASC"
        else:
            query += " ORDER BY parsed_date ASC, COALESCE(parsed_time, '23:59') ASC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def search_past_items(
        self,
        query_text: str,
        top_k: int = 5,
        only_active: bool = False
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            sql = "SELECT * FROM tasks WHERE status = 'Active' ORDER BY created_at DESC" if only_active else "SELECT * FROM tasks ORDER BY created_at DESC"
            rows = conn.execute(sql).fetchall()

        if not rows or not query_text.strip():
            return []

        query_vec = TextVectorizer.text_to_vector(query_text)
        query_lemmas = set(TextVectorizer.extract_lemmas(query_text).split())

        matrix = np.vstack([
            np.frombuffer(r["embedding"], dtype=np.float32) if r["embedding"]
            else np.zeros(VECTOR_DIM, dtype=np.float32)
            for r in rows
        ])

        cosine_scores = np.dot(matrix, query_vec)

        results = []
        for idx, row in enumerate(rows):
            score = float(cosine_scores[idx])
            row_lemmas = set((row["lemmas"] or "").split())

            common_lemmas = query_lemmas.intersection(row_lemmas)
            if common_lemmas:
                score += 0.25 * (len(common_lemmas) / max(len(query_lemmas), 1))

            if score >= 0.22:
                item_dict = dict(row)
                item_dict.pop("embedding", None)
                item_dict["similarity"] = round(min(score, 1.0), 3)
                results.append(item_dict)

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def get_history(
        self,
        limit: int = 50,
        offset: int = 0,
        intent_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        sort_by: str = "created_desc"
    ) -> List[Dict[str, Any]]:
        """История запросов с поддержкой фильтрации и сортировки по типу задачи (Task / Meeting)."""
        query = """
            SELECT id, intent, raw_text, action, parsed_date, parsed_time,
                   date_in_past, status, parse_method, created_at
            FROM tasks
            WHERE 1=1
        """
        params: List[Any] = []

        if intent_filter in ("Task", "Meeting"):
            query += " AND intent = ?"
            params.append(intent_filter)

        if status_filter in ("Active", "Done"):
            query += " AND status = ?"
            params.append(status_filter)

        if sort_by == "type":
            query += " ORDER BY intent ASC, COALESCE(parsed_date, '9999-12-31') ASC, created_at DESC"
        elif sort_by == "date":
            query += " ORDER BY COALESCE(parsed_date, '9999-12-31') ASC, COALESCE(parsed_time, '23:59') ASC"
        else:
            query += " ORDER BY created_at DESC"

        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def mark_done(self, task_id: int) -> bool:
        """Переводит задачу в статус Done."""
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE tasks SET status = 'Done' WHERE id = ?", (task_id,))
            conn.commit()
            return cur.rowcount > 0

    def delete_item(self, task_id: int) -> bool:
        """Удаляет задачу по её ID."""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cur.rowcount > 0

    def find_and_delete_by_query(self, query_text: str) -> Optional[Dict[str, Any]]:
        """Находит наиболее подходящую задачу по голосовому описанию и удаляет её."""
        candidates = self.search_past_items(query_text, top_k=1)
        if not candidates:
            return None
        target = candidates[0]
        if self.delete_item(target["id"]):
            return target
        return None

    def find_and_complete_by_query(self, query_text: str) -> Optional[Dict[str, Any]]:
        """Находит активную задачу по голосовому описанию и переводит в статус Done."""
        candidates = self.search_past_items(query_text, top_k=1, only_active=True)
        if not candidates:
            candidates = self.search_past_items(query_text, top_k=1, only_active=False)
        if not candidates:
            return None
        target = candidates[0]
        if self.mark_done(target["id"]):
            target["status"] = "Done"
            return target
        return None
