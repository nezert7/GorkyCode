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

morph = pymorphy3.MorphAnalyzer()

VECTOR_DIM = 512
VALID_INTENTS = ("Task", "Reminder", "Meeting")


def get_intent_label_ru(intent: Optional[str]) -> str:
    if intent == "Meeting":
        return "Встреча"
    if intent == "Reminder":
        return "Напоминание"
    return "Задача"


class TextVectorizer:
    """Превращает русский текст в нормализованные леммы и 512-мерный вектор NumPy (float32)."""

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
    Двусторонняя синхронизация с системным календарём:
    - Создание, удаление и обновление событий в Apple Calendar (macOS) с будильником за 60 минут.
    - Экспорт актуального состояния в vorona_calendar.ics.
    - Отправка системных фоновых уведомлений ОС за 1 час до задачи.
    """

    ICS_FILE_PATH = "vorona_calendar.ics"

    @classmethod
    def sync_event_to_os_calendar(cls, item: Dict[str, Any]) -> bool:
        """Добавляет событие в нативный календарь macOS (Apple Calendar) с напоминанием за 1 час."""
        parsed_date = item.get("parsed_date")
        if not parsed_date:
            return False

        task_id = item.get("id", 0)
        parsed_time = item.get("parsed_time") or "09:00"
        raw_title = item.get("action") or "Задача Ворона"
        intent_label = get_intent_label_ru(item.get("intent"))
        title = f"[{intent_label}] {raw_title}".replace('"', '\\"')
        description = f"{intent_label} из голосового ассистента Ворона: {raw_title} [VORONA_ID:{task_id}]".replace('"', '\\"')

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
                            set newEvent to make new event at end with properties {{summary:"{title}", start date:startDate, end date:endDate, description:"{description}"}}
                            tell newEvent
                                make new display alarm at end with properties {{trigger interval:-60}}
                            end tell
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
    def remove_event_from_os_calendar(cls, item: Dict[str, Any]) -> bool:
        """Удаляет событие из нативного календаря macOS по ID или названию задачи."""
        if not item:
            return False

        task_id = item.get("id", 0)
        raw_title = (item.get("action") or "").replace('"', '\\"')
        intent_label = get_intent_label_ru(item.get("intent"))
        prefixed_title = f"[{intent_label}] {raw_title}"
        marker = f"[VORONA_ID:{task_id}]"

        if sys.platform == "darwin":
            try:
                applescript = f'''
                tell application "Calendar"
                    repeat with cal in calendars
                        tell cal
                            try
                                delete (every event whose description contains "{marker}")
                            end try
                            if "{raw_title}" is not "" then
                                try
                                    delete (every event whose summary is "{raw_title}" or summary is "{prefixed_title}")
                                end try
                            end if
                        end tell
                    end repeat
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
    def send_os_notification(cls, item: Dict[str, Any]) -> None:
        """Отправляет нативное фоновое уведомление ОС за 1 час до начала события."""
        kind = get_intent_label_ru(item.get("intent"))
        action = (item.get("action") or "Событие").replace('"', '\\"')
        time_str = item.get("parsed_time") or ""
        title = f"Ворона — {kind} через час"
        msg = f"{action} (в {time_str})" if time_str else action

        if sys.platform == "darwin":
            try:
                script = f'display notification "{msg}" with title "{title}" sound name "Glass"'
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        elif sys.platform == "win32":
            try:
                ps_cmd = (
                    f"[reflection.assembly]::loadwithpartialname('System.Windows.Forms');"
                    f"[System.Windows.Forms.MessageBox]::Show('{msg}', '{title}')"
                )
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    @classmethod
    def export_all_to_ics(cls, items: List[Dict[str, Any]]) -> str:
        """Генерирует и сохраняет .ics файл только для существующих задач."""
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
            kind = get_intent_label_ru(it.get("intent"))

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:[{kind}] {summary}",
                f"DESCRIPTION:Создано голосовым ассистентом Ворона ({it.get('raw_text', '')}) [VORONA_ID:{it.get('id', 0)}]",
                f"STATUS:{'CONFIRMED' if it.get('status') == 'Active' else 'COMPLETED'}",
                "BEGIN:VALARM",
                "TRIGGER:-PT60M",
                "ACTION:DISPLAY",
                f"DESCRIPTION:Напоминание: {summary}",
                "END:VALARM",
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
    Слой хранения данных SQLite + Поиск на NumPy + 3 типа (Task, Reminder, Meeting) +
    Синхронизация с Календарём при создании, изменении и удалении.
    """

    def __init__(self, db_path: str = "events.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _is_real_db(self) -> bool:
        return self.db_path != ":memory:" and not self.db_path.startswith("test")

    def _init_db(self) -> None:
        """Создаёт таблицу tasks и автоматически мигрирует старую схему под 3 типа ('Task','Meeting','Reminder') и поле notified."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
            ).fetchone()

            if row is not None:
                table_sql = row["sql"] or ""
                if "'Reminder'" not in table_sql:
                    conn.execute("ALTER TABLE tasks RENAME TO tasks_old;")
                    conn.execute("""
                        CREATE TABLE tasks (
                            id           INTEGER PRIMARY KEY AUTOINCREMENT,
                            intent       TEXT    NOT NULL CHECK (intent IN ('Task','Meeting','Reminder')),
                            raw_text     TEXT    NOT NULL,
                            action       TEXT    NOT NULL,
                            parsed_date  TEXT    CHECK (parsed_date IS NULL OR parsed_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
                            parsed_time  TEXT    CHECK (parsed_time IS NULL OR parsed_time GLOB '[0-2][0-9]:[0-5][0-9]'),
                            date_in_past INTEGER NOT NULL DEFAULT 0 CHECK (date_in_past IN (0,1)),
                            status       TEXT    NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Done')),
                            parse_method TEXT    NOT NULL CHECK (parse_method IN ('llm','regex')),
                            created_at   TEXT    NOT NULL,
                            lemmas       TEXT,
                            embedding    BLOB,
                            notified     INTEGER NOT NULL DEFAULT 0
                        );
                    """)
                    conn.execute("""
                        INSERT INTO tasks (
                            id, intent, raw_text, action, parsed_date, parsed_time,
                            date_in_past, status, parse_method, created_at, lemmas, embedding
                        )
                        SELECT id, intent, raw_text, action, parsed_date, parsed_time,
                               date_in_past, status, parse_method, created_at, lemmas, embedding
                        FROM tasks_old;
                    """)
                    conn.execute("DROP TABLE tasks_old;")
                    conn.commit()
                else:
                    cols = [c["name"] for c in conn.execute("PRAGMA table_info(tasks)").fetchall()]
                    if "notified" not in cols:
                        conn.execute("ALTER TABLE tasks ADD COLUMN notified INTEGER NOT NULL DEFAULT 0;")
                        conn.commit()
            else:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        intent       TEXT    NOT NULL CHECK (intent IN ('Task','Meeting','Reminder')),
                        raw_text     TEXT    NOT NULL,
                        action       TEXT    NOT NULL,
                        parsed_date  TEXT    CHECK (parsed_date IS NULL OR parsed_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
                        parsed_time  TEXT    CHECK (parsed_time IS NULL OR parsed_time GLOB '[0-2][0-9]:[0-5][0-9]'),
                        date_in_past INTEGER NOT NULL DEFAULT 0 CHECK (date_in_past IN (0,1)),
                        status       TEXT    NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Done')),
                        parse_method TEXT    NOT NULL CHECK (parse_method IN ('llm','regex')),
                        created_at   TEXT    NOT NULL,
                        lemmas       TEXT,
                        embedding    BLOB,
                        notified     INTEGER NOT NULL DEFAULT 0
                    );
                """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks (parsed_date);")
            conn.commit()

    def get_item_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, intent, raw_text, action, parsed_date, parsed_time,
                       date_in_past, status, parse_method, created_at, notified
                FROM tasks WHERE id = ?
                """,
                (task_id,)
            ).fetchone()
            return dict(row) if row else None

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
        if intent not in VALID_INTENTS:
            intent = "Task"

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
                    date_in_past, status, parse_method, created_at, lemmas, embedding, notified
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?, ?, 0)
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

        if self._is_real_db():
            CalendarIntegration.sync_event_to_os_calendar(saved)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200))

        return saved

    def update_item(
        self,
        task_id: int,
        action: Optional[str] = None,
        parsed_date: Optional[str] = "__UNSET__",
        parsed_time: Optional[str] = "__UNSET__",
        intent: Optional[str] = None,
        status: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Обновляет существующую задачу/напоминание/встречу и синхронизирует изменения с Календарём."""
        old_item = self.get_item_by_id(task_id)
        if not old_item:
            return None

        new_action = (action.strip() if action and action.strip() else old_item["action"])
        new_date = old_item["parsed_date"] if parsed_date == "__UNSET__" else parsed_date
        new_time = old_item["parsed_time"] if parsed_time == "__UNSET__" else parsed_time
        new_intent = intent if intent in VALID_INTENTS else old_item["intent"]
        new_status = status if status in ("Active", "Done") else old_item["status"]

        today_str = datetime.now().strftime("%Y-%m-%d")
        date_in_past = 1 if (new_date and new_date < today_str) else 0

        search_target = f"{new_action} {old_item['raw_text']}"
        lemmas = TextVectorizer.extract_lemmas(search_target)
        vector_bytes = TextVectorizer.text_to_vector(search_target).tobytes()

        with self._get_conn() as conn:
            conn.execute("""
                UPDATE tasks
                SET action = ?, parsed_date = ?, parsed_time = ?, intent = ?,
                    status = ?, date_in_past = ?, lemmas = ?, embedding = ?, notified = 0
                WHERE id = ?
            """, (
                new_action, new_date, new_time, new_intent,
                new_status, date_in_past, lemmas, vector_bytes, task_id
            ))
            conn.commit()

        updated_item = self.get_item_by_id(task_id)

        if self._is_real_db() and updated_item:
            CalendarIntegration.remove_event_from_os_calendar(old_item)
            if updated_item.get("parsed_date") and updated_item.get("status") == "Active":
                CalendarIntegration.sync_event_to_os_calendar(updated_item)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200))

        return updated_item

    def find_and_update_by_query(
        self,
        query_text: str,
        new_action: Optional[str] = None,
        new_date: Optional[str] = None,
        new_time: Optional[str] = None,
        new_intent: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Находит задачу по голосовому описанию и обновляет её поля."""
        candidates = self.search_past_items(query_text, top_k=1, only_active=True)
        if not candidates:
            candidates = self.search_past_items(query_text, top_k=1, only_active=False)
        if not candidates:
            return None

        target = candidates[0]
        return self.update_item(
            task_id=target["id"],
            action=new_action if new_action else None,
            parsed_date=new_date if new_date is not None else "__UNSET__",
            parsed_time=new_time if new_time is not None else "__UNSET__",
            intent=new_intent if new_intent in VALID_INTENTS else None
        )

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

        if intent_filter in VALID_INTENTS:
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
            sql = (
                "SELECT * FROM tasks WHERE status = 'Active' ORDER BY created_at DESC"
                if only_active
                else "SELECT * FROM tasks ORDER BY created_at DESC"
            )
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

            if score >= 0.20:
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
        query = """
            SELECT id, intent, raw_text, action, parsed_date, parsed_time,
                   date_in_past, status, parse_method, created_at
            FROM tasks
            WHERE 1=1
        """
        params: List[Any] = []

        if intent_filter in VALID_INTENTS:
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
        """Переводит задачу в статус Done и обновляет календарь."""
        item = self.get_item_by_id(task_id)
        if not item:
            return False

        with self._get_conn() as conn:
            cur = conn.execute("UPDATE tasks SET status = 'Done' WHERE id = ?", (task_id,))
            conn.commit()
            ok = cur.rowcount > 0

        if ok and self._is_real_db():
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200))
        return ok

    def delete_item(self, task_id: int) -> bool:
        """Удаляет задачу по ID из SQLite И из системного Календаря macOS / .ics."""
        item_to_remove = self.get_item_by_id(task_id)
        if not item_to_remove:
            return False

        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            deleted = cur.rowcount > 0

        if deleted and self._is_real_db():
            CalendarIntegration.remove_event_from_os_calendar(item_to_remove)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200))

        return deleted

    def find_and_delete_by_query(self, query_text: str) -> Optional[Dict[str, Any]]:
        """Находит задачу по голосовому описанию и удаляет её из БД и Календаря."""
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

    def check_and_trigger_upcoming_notifications(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Проверяет активные задачи/напоминания/встречи, до которых осталось <= 60 минут,
        отправляет системное уведомление и помечает notified = 1.
        """
        now_dt = now or datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")
        tomorrow_str = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, intent, raw_text, action, parsed_date, parsed_time, status
                FROM tasks
                WHERE status = 'Active'
                  AND COALESCE(notified, 0) = 0
                  AND parsed_date IN (?, ?)
                  AND parsed_time IS NOT NULL
            """, (today_str, tomorrow_str)).fetchall()

        triggered: List[Dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            try:
                event_dt = datetime.strptime(
                    f"{item['parsed_date']} {item['parsed_time']}", "%Y-%m-%d %H:%M"
                )
            except ValueError:
                continue

            diff_seconds = (event_dt - now_dt).total_seconds()
            # Уведомляем, если до задачи осталось от 0 до 60 минут (3600 сек)
            if 0 <= diff_seconds <= 3600:
                with self._get_conn() as conn:
                    conn.execute("UPDATE tasks SET notified = 1 WHERE id = ?", (item["id"],))
                    conn.commit()
                if self._is_real_db():
                    CalendarIntegration.send_os_notification(item)
                triggered.append(item)

        return triggered