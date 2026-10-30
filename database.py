import os
import sys
import sqlite3
import re
import json
import base64
import hashlib
import subprocess
import httpx
import numpy as np
import pymorphy3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Sequence
from dotenv import load_dotenv

load_dotenv(override=True)

morph = pymorphy3.MorphAnalyzer()

VECTOR_DIM = 512
VALID_INTENTS = ("Task", "Reminder", "Meeting")


def get_intent_label_ru(intent: Optional[str]) -> str:
    if intent == "Meeting":
        return "Встреча"
    if intent == "Reminder":
        return "Напоминание"
    return "Задача"


# =====================================================================
# ДРАЙВЕР ОБЛАЧНОЙ БАЗЫ TURSO (SQLite over HTTPS /v2/pipeline)
# =====================================================================

class TursoCursor:
    """Курсор, полностью совместимый с интерфейсом sqlite3.Cursor."""

    def __init__(self, conn: "TursoConnection"):
        self.conn = conn
        self._rows: List[Dict[str, Any]] = []
        self.lastrowid: Optional[int] = None
        self.rowcount: int = 0

    def execute(self, sql: str, params: Sequence[Any] = ()) -> "TursoCursor":
        result = self.conn._execute_remote(sql, params)
        cols = [c.get("name", f"col_{i}") for i, c in enumerate(result.get("cols", []))]
        raw_rows = result.get("rows", [])

        decoded_rows: List[Dict[str, Any]] = []
        for r in raw_rows:
            row_dict = {
                cols[i]: self.conn._decode_cell(cell)
                for i, cell in enumerate(r)
            }
            decoded_rows.append(row_dict)

        self._rows = decoded_rows
        raw_last_id = result.get("last_insert_rowid")
        self.lastrowid = int(raw_last_id) if raw_last_id is not None else None
        self.rowcount = int(result.get("affected_row_count", 0))
        return self

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self._rows)


class TursoConnection:
    """Соединение с облачной БД Turso через HTTP/1.1 Keep-Alive, совместимое с sqlite3.Connection."""

    def __init__(self, pipeline_url: str, auth_token: str, http_client: httpx.Client):
        self.pipeline_url = pipeline_url
        self.auth_token = auth_token
        self.http_client = http_client

    def __enter__(self) -> "TursoConnection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def cursor(self) -> TursoCursor:
        return TursoCursor(self)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> TursoCursor:
        cur = TursoCursor(self)
        return cur.execute(sql, params)

    def commit(self) -> None:
        pass

    @staticmethod
    def _encode_arg(val: Any) -> Dict[str, Any]:
        if val is None:
            return {"type": "null"}
        if isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        if isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        if isinstance(val, float):
            return {"type": "float", "value": val}
        if isinstance(val, (bytes, bytearray, memoryview)):
            return {
                "type": "blob",
                "base64": base64.b64encode(bytes(val)).decode("ascii")
            }
        return {"type": "text", "value": str(val)}

    @staticmethod
    def _decode_cell(cell: Dict[str, Any]) -> Any:
        cell_type = cell.get("type")
        if cell_type == "null" or cell_type is None:
            return None
        if cell_type == "integer":
            return int(cell["value"])
        if cell_type == "float":
            return float(cell["value"])
        if cell_type == "blob":
            return base64.b64decode(cell.get("base64", ""))
        return str(cell.get("value", ""))

    def _execute_remote(self, sql: str, params: Sequence[Any] = ()) -> Dict[str, Any]:
        stmt: Dict[str, Any] = {"sql": sql}
        if params:
            stmt["args"] = [self._encode_arg(p) for p in params]

        payload = {
            "requests": [
                {"type": "execute", "stmt": stmt},
                {"type": "close"}
            ]
        }
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json"
        }

        resp = self.http_client.post(self.pipeline_url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise sqlite3.OperationalError(
                f"Turso HTTP Error {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}

        first = results[0]
        if first.get("type") == "error":
            err_msg = first.get("error", {}).get("message", "Unknown Turso SQL error")
            if "UNIQUE" in err_msg.upper() or "CONSTRAINT" in err_msg.upper():
                raise sqlite3.IntegrityError(err_msg)
            raise sqlite3.OperationalError(err_msg)

        return first.get("response", {}).get("result", {})


# =====================================================================
# ВЕКТОРИЗАЦИЯ И КАЛЕНДАРЬ
# =====================================================================

class TextVectorizer:
    """Превращает русский текст в нормализованные леммы и 512-мерный вектор NumPy (float32)."""

    STOP_LEMMAS = {
        "задача", "встреча", "напоминание", "напомнить", "дело", "событие",
        "перенести", "изменить", "поменять", "сдвинуть", "отложить", "переименовать",
        "исправить", "заменить", "обновить", "удалить", "убрать", "отменить",
        "выполнить", "завершить", "отметить", "сегодня", "завтра", "послезавтра"
    }

    @staticmethod
    def extract_lemmas(text: str) -> str:
        words = re.findall(r"[а-яёa-z0-9]+", text.lower())
        lemmas = [morph.parse(w)[0].normal_form for w in words if len(w) > 1]
        return " ".join(lemmas)

    @classmethod
    def extract_meaningful_lemmas(cls, text: str) -> List[str]:
        all_lemmas = cls.extract_lemmas(text).split()
        meaningful = [l for l in all_lemmas if l not in cls.STOP_LEMMAS]
        return meaningful if meaningful else all_lemmas

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
    Кроссплатформенная синхронизация с календарём и уведомлениями:
    - macOS: Apple Calendar (osascript) + нативные баннеры.
    - Windows: Автообновление .ics файла + нативные Toast-уведомления Windows 10/11.
    """

    ICS_FILE_PATH = "vorona_calendar.ics"

    @classmethod
    def sync_event_to_os_calendar(cls, item: Dict[str, Any]) -> bool:
        parsed_date = item.get("parsed_date")
        if not parsed_date:
            return False

        task_id = item.get("id", 0)
        parsed_time = item.get("parsed_time") or "09:00"
        raw_title = item.get("action") or "Задача Ворона"
        intent_label = get_intent_label_ru(item.get("intent"))

        try:
            dt = datetime.strptime(f"{parsed_date} {parsed_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return False

        # 1. macOS -> Apple Calendar
        if sys.platform == "darwin":
            title = f"[{intent_label}] {raw_title}".replace('"', '\\"')
            description = f"{intent_label} из голосового ассистента Ворона: {raw_title} [VORONA_ID:{task_id}]".replace('"', '\\"')
            try:
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

        return True  # Для Windows и других ОС календарь синхронизируется через .ics подписку

    @classmethod
    def remove_event_from_os_calendar(cls, item: Dict[str, Any]) -> bool:
        if not item:
            return False

        task_id = item.get("id", 0)
        raw_title = item.get("action") or ""
        intent_label = get_intent_label_ru(item.get("intent"))
        marker = f"[VORONA_ID:{task_id}]"

        if sys.platform == "darwin":
            safe_raw = raw_title.replace('"', '\\"')
            prefixed_title = f"[{intent_label}] {safe_raw}"
            try:
                applescript = f'''
                tell application "Calendar"
                    repeat with cal in calendars
                        tell cal
                            try
                                delete (every event whose description contains "{marker}")
                            end try
                            if "{safe_raw}" is not "" then
                                try
                                    delete (every event whose summary is "{safe_raw}" or summary is "{prefixed_title}")
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

        return True

    @classmethod
    def send_os_notification(cls, item: Dict[str, Any]) -> None:
        kind = get_intent_label_ru(item.get("intent"))
        raw_action = item.get("action") or "Событие"
        time_str = item.get("parsed_time") or ""
        title = f"Ворона — {kind} через час"
        msg = f"{raw_action} (в {time_str})" if time_str else raw_action

        if sys.platform == "darwin":
            safe_title = title.replace('"', '\\"')
            safe_msg = msg.replace('"', '\\"')
            try:
                script = f'display notification "{safe_msg}" with title "{safe_title}" sound name "Glass"'
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

        elif sys.platform == "win32":
            win_title = title.replace("'", "''").replace('"', "")
            win_msg = msg.replace("'", "''").replace('"', "")
            try:
                ps_toast = f"""
                try {{
                    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
                    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
                    $template = "<toast><visual><binding template='ToastGeneric'><text>{win_title}</text><text>{win_msg}</text></binding></visual><audio src='ms-winsoundevent:Notification.Default'/></toast>"
                    $xml.LoadXml($template)
                    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Vorona Voice Assistant').Show($toast)
                }} catch {{
                    Add-Type -AssemblyName System.Windows.Forms
                    Add-Type -AssemblyName System.Drawing
                    $notify = New-Object System.Windows.Forms.NotifyIcon
                    $notify.Icon = [System.Drawing.SystemIcons]::Information
                    $notify.Visible = $true
                    $notify.ShowBalloonTip(7000, '{win_title}', '{win_msg}', [System.Windows.Forms.ToolTipIcon]::Info)
                    Start-Sleep -Seconds 8
                    $notify.Dispose()
                }}
                """
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_toast],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    @classmethod
    def export_all_to_ics(cls, items: List[Dict[str, Any]]) -> str:
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


# =====================================================================
# МЕНЕДЖЕР БАЗЫ ДАННЫХ (Turso Cloud SQLite + Local SQLite Fallback)
# =====================================================================

class DatabaseManager:
    """Мультипользовательский слой хранения (Turso ИЛИ локальный SQLite) + NumPy поиск."""

    def __init__(self, db_path: str = "events.db"):
        self.db_path = db_path
        self.turso_url: Optional[str] = None
        self.turso_token: Optional[str] = None
        self._turso_http: Optional[httpx.Client] = None

        if self._is_real_db():
            raw_url = (os.getenv("TURSO_DATABASE_URL") or "").strip()
            raw_token = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()
            if raw_url and raw_token:
                clean_url = re.sub(r"^libsql://", "https://", raw_url).rstrip("/")
                if not clean_url.endswith("/v2/pipeline"):
                    clean_url += "/v2/pipeline"
                self.turso_url = clean_url
                self.turso_token = raw_token
                self._turso_http = httpx.Client(timeout=15.0)
                print(f"☁️ [ОБЛАЧНАЯ БД] Подключена база Turso SQLite: {raw_url}")

        self._init_db()

        if self.turso_url:
            self._migrate_local_sqlite_to_turso_if_needed()

    def _get_conn(self):
        if self.turso_url and self.turso_token and self._turso_http:
            return TursoConnection(self.turso_url, self.turso_token, self._turso_http)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _is_real_db(self) -> bool:
        return self.db_path != ":memory:" and not self.db_path.startswith("test")

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT    NOT NULL,
                    created_at    TEXT    NOT NULL
                );
            """)

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
                            user_id      INTEGER NOT NULL DEFAULT 1,
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
                            id, user_id, intent, raw_text, action, parsed_date, parsed_time,
                            date_in_past, status, parse_method, created_at, lemmas, embedding
                        )
                        SELECT id, 1, intent, raw_text, action, parsed_date, parsed_time,
                               date_in_past, status, parse_method, created_at, lemmas, embedding
                        FROM tasks_old;
                    """)
                    conn.execute("DROP TABLE tasks_old;")
                    conn.commit()
                else:
                    cols = [c["name"] for c in conn.execute("PRAGMA table_info(tasks)").fetchall()]
                    if "notified" not in cols:
                        conn.execute("ALTER TABLE tasks ADD COLUMN notified INTEGER NOT NULL DEFAULT 0;")
                    if "user_id" not in cols:
                        conn.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1;")
                    conn.commit()
            else:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id      INTEGER NOT NULL DEFAULT 1,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks (user_id, created_at DESC);")
            conn.commit()

    def _migrate_local_sqlite_to_turso_if_needed(self) -> None:
        if not os.path.exists(self.db_path):
            return
        try:
            with self._get_conn() as cloud_conn:
                cloud_tasks_cnt = cloud_conn.execute("SELECT COUNT(*) AS cnt FROM tasks").fetchone()
                if cloud_tasks_cnt and int(cloud_tasks_cnt["cnt"]) > 0:
                    return

                local_conn = sqlite3.connect(self.db_path)
                local_conn.row_factory = sqlite3.Row

                try:
                    local_users = local_conn.execute("SELECT * FROM users").fetchall()
                    for u in local_users:
                        cloud_conn.execute(
                            "INSERT OR IGNORE INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                            (u["id"], u["username"], u["password_hash"], u["created_at"])
                        )
                except Exception:
                    pass

                local_tasks = local_conn.execute("SELECT * FROM tasks").fetchall()
                for t in local_tasks:
                    t_dict = dict(t)
                    cloud_conn.execute("""
                        INSERT OR IGNORE INTO tasks (
                            id, user_id, intent, raw_text, action, parsed_date, parsed_time,
                            date_in_past, status, parse_method, created_at, lemmas, embedding, notified
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        t_dict.get("id"),
                        t_dict.get("user_id", 1),
                        t_dict.get("intent", "Task"),
                        t_dict.get("raw_text", ""),
                        t_dict.get("action", ""),
                        t_dict.get("parsed_date"),
                        t_dict.get("parsed_time"),
                        t_dict.get("date_in_past", 0),
                        t_dict.get("status", "Active"),
                        t_dict.get("parse_method", "llm"),
                        t_dict.get("created_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
                        t_dict.get("lemmas"),
                        t_dict.get("embedding"),
                        t_dict.get("notified", 0)
                    ))
                local_conn.close()
                if local_tasks:
                    print(f"🚀 [МИГРАЦИЯ В ОБЛАКО] Перенесено {len(local_tasks)} задач из локальной БД в Turso!")
        except Exception as exc:
            print(f"⚠️ [МИГРАЦИЯ] Инфо: {exc}")

    def create_user(self, username: str, password_hash: str) -> Optional[Dict[str, Any]]:
        clean_username = username.strip()
        if not clean_username:
            return None
        created_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (clean_username, password_hash, created_at)
                )
                conn.commit()
                new_user_id = cur.lastrowid
                return {
                    "id": new_user_id,
                    "username": clean_username,
                    "created_at": created_at
                }
        except sqlite3.IntegrityError:
            return None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
                (username.strip(),)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_item_by_id(self, task_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            if user_id is not None:
                row = conn.execute(
                    """
                    SELECT id, user_id, intent, raw_text, action, parsed_date, parsed_time,
                           date_in_past, status, parse_method, created_at, notified
                    FROM tasks WHERE id = ? AND user_id = ?
                    """,
                    (task_id, user_id)
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id, user_id, intent, raw_text, action, parsed_date, parsed_time,
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
        now_override: Optional[datetime] = None,
        user_id: int = 1
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
                    user_id, intent, raw_text, action, parsed_date, parsed_time,
                    date_in_past, status, parse_method, created_at, lemmas, embedding, notified
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?, ?, 0)
            """, (
                user_id, intent, raw_text, action, parsed_date, parsed_time,
                date_in_past, parse_method, created_at, lemmas, vector_bytes
            ))
            conn.commit()
            new_id = cursor.lastrowid

        saved = {
            "id": new_id,
            "user_id": user_id,
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
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200, user_id=user_id))

        return saved

    def update_item(
        self,
        task_id: int,
        action: Optional[str] = None,
        parsed_date: Optional[str] = "__UNSET__",
        parsed_time: Optional[str] = "__UNSET__",
        intent: Optional[str] = None,
        status: Optional[str] = None,
        user_id: int = 1
    ) -> Optional[Dict[str, Any]]:
        old_item = self.get_item_by_id(task_id, user_id=user_id)
        if not old_item:
            return None

        new_action = (action.strip() if action and action.strip() else old_item["action"])
        new_date = old_item["parsed_date"] if parsed_date == "__UNSET__" else parsed_date
        new_time = old_item["parsed_time"] if parsed_time == "__UNSET__" else parsed_time
        new_intent = intent if intent in VALID_INTENTS else old_item["intent"]
        new_status = status if status in ("Active", "Done") else old_item["status"]

        now_dt = datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")

        if new_time and not new_date and parsed_date == "__UNSET__":
            now_time_str = now_dt.strftime("%H:%M")
            if new_time <= now_time_str:
                new_date = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                new_date = today_str

        date_in_past = 1 if (new_date and new_date < today_str) else 0

        search_target = f"{new_action} {old_item['raw_text']}"
        lemmas = TextVectorizer.extract_lemmas(search_target)
        vector_bytes = TextVectorizer.text_to_vector(search_target).tobytes()

        with self._get_conn() as conn:
            conn.execute("""
                UPDATE tasks
                SET action = ?, parsed_date = ?, parsed_time = ?, intent = ?,
                    status = ?, date_in_past = ?, lemmas = ?, embedding = ?, notified = 0
                WHERE id = ? AND user_id = ?
            """, (
                new_action, new_date, new_time, new_intent,
                new_status, date_in_past, lemmas, vector_bytes, task_id, user_id
            ))
            conn.commit()

        updated_item = self.get_item_by_id(task_id, user_id=user_id)

        if self._is_real_db() and updated_item:
            CalendarIntegration.remove_event_from_os_calendar(old_item)
            if updated_item.get("parsed_date") and updated_item.get("status") == "Active":
                CalendarIntegration.sync_event_to_os_calendar(updated_item)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200, user_id=user_id))

        return updated_item

    def find_best_matching_item(
        self,
        query_text: Optional[str] = None,
        target_id: Optional[int] = None,
        intent_hint: Optional[str] = None,
        only_active: bool = True,
        user_id: int = 1
    ) -> Optional[Dict[str, Any]]:
        if target_id is not None:
            try:
                exact_item = self.get_item_by_id(int(target_id), user_id=user_id)
                if exact_item:
                    return exact_item
            except (ValueError, TypeError):
                pass

        with self._get_conn() as conn:
            sql = (
                "SELECT * FROM tasks WHERE user_id = ? AND status = 'Active' ORDER BY created_at DESC, id DESC"
                if only_active
                else "SELECT * FROM tasks WHERE user_id = ? ORDER BY status ASC, created_at DESC, id DESC"
            )
            rows = conn.execute(sql, (user_id,)).fetchall()

        if not rows and only_active:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                    (user_id,)
                ).fetchall()

        if not rows:
            return None

        clean_q = (query_text or "").strip().lower()
        meaningful_lemmas = set(TextVectorizer.extract_meaningful_lemmas(clean_q))
        raw_words = [
            w for w in re.findall(r"[а-яёa-z0-9]+", clean_q)
            if len(w) >= 3 and morph.parse(w)[0].normal_form not in TextVectorizer.STOP_LEMMAS
        ]

        if not meaningful_lemmas or clean_q in ("ее", "её", "эту", "последнюю", "задачу", "встречу", "напоминание"):
            if intent_hint in VALID_INTENTS:
                for r in rows:
                    if r["intent"] == intent_hint:
                        item = dict(r)
                        item.pop("embedding", None)
                        return item
            item = dict(rows[0])
            item.pop("embedding", None)
            return item

        query_vec = TextVectorizer.text_to_vector(" ".join(meaningful_lemmas) or clean_q)
        matrix = np.vstack([
            np.frombuffer(r["embedding"], dtype=np.float32)
            if r["embedding"] and len(r["embedding"]) == VECTOR_DIM * 4
            else TextVectorizer.text_to_vector(f"{r['action']} {r['raw_text']}")
            for r in rows
        ])
        cosine_scores = np.dot(matrix, query_vec)

        best_item = None
        best_score = -1.0

        for idx, row in enumerate(rows):
            action_lower = (row["action"] or "").lower()
            raw_lower = (row["raw_text"] or "").lower()
            row_lemmas = set((row["lemmas"] or TextVectorizer.extract_lemmas(f"{action_lower} {raw_lower}")).split())

            score = float(cosine_scores[idx]) * 0.55

            common_lemmas = meaningful_lemmas.intersection(row_lemmas)
            if common_lemmas:
                score += 0.50 * (len(common_lemmas) / max(len(meaningful_lemmas), 1))

            for w in raw_words:
                stem = w[:4] if len(w) >= 5 else w[:3]
                if w in action_lower or w in raw_lower:
                    score += 0.35
                elif len(stem) >= 3 and (stem in action_lower or stem in raw_lower):
                    score += 0.22

            if intent_hint and row["intent"] == intent_hint:
                score += 0.12

            if row["status"] == "Active":
                score += 0.08

            if score > best_score:
                best_score = score
                best_item = dict(row)
                best_item.pop("embedding", None)

        if best_item and best_score >= 0.18:
            return best_item

        if intent_hint in VALID_INTENTS:
            typed_rows = [r for r in rows if r["intent"] == intent_hint]
            if len(typed_rows) == 1:
                item = dict(typed_rows[0])
                item.pop("embedding", None)
                return item
        if len(rows) == 1:
            item = dict(rows[0])
            item.pop("embedding", None)
            return item

        return None

    def find_and_update_by_query(
        self,
        query_text: Optional[str],
        target_id: Optional[int] = None,
        new_action: Optional[str] = None,
        new_date: Optional[str] = None,
        new_time: Optional[str] = None,
        new_intent: Optional[str] = None,
        intent_hint: Optional[str] = None,
        user_id: int = 1
    ) -> Optional[Dict[str, Any]]:
        target = self.find_best_matching_item(
            query_text=query_text,
            target_id=target_id,
            intent_hint=intent_hint,
            only_active=True,
            user_id=user_id
        )
        if not target:
            return None

        return self.update_item(
            task_id=target["id"],
            action=new_action if new_action else None,
            parsed_date=new_date if new_date is not None else "__UNSET__",
            parsed_time=new_time if new_time is not None else "__UNSET__",
            intent=new_intent if new_intent in VALID_INTENTS else None,
            user_id=user_id
        )

    def check_meeting_conflict(self, parsed_date: str, parsed_time: str, user_id: int = 1) -> List[Dict[str, Any]]:
        if not parsed_date or not parsed_time:
            return []
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, user_id, intent, action, parsed_date, parsed_time
                FROM tasks
                WHERE user_id = ? AND parsed_date = ? AND parsed_time = ? AND status = 'Active'
            """, (user_id, parsed_date, parsed_time)).fetchall()
            return [dict(r) for r in rows]

    def get_items_by_period(
        self,
        start_date: str,
        end_date: str,
        intent_filter: Optional[str] = None,
        sort_by: str = "date",
        user_id: int = 1
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT id, user_id, intent, raw_text, action, parsed_date, parsed_time,
                   date_in_past, status, parse_method, created_at
            FROM tasks
            WHERE user_id = ? AND parsed_date >= ? AND parsed_date <= ? AND status = 'Active'
        """
        params: List[Any] = [user_id, start_date, end_date]

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
        only_active: bool = False,
        user_id: int = 1
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            sql = (
                "SELECT * FROM tasks WHERE user_id = ? AND status = 'Active' ORDER BY created_at DESC"
                if only_active
                else "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC"
            )
            rows = conn.execute(sql, (user_id,)).fetchall()

        if not rows or not query_text.strip():
            return []

        query_vec = TextVectorizer.text_to_vector(query_text)
        query_lemmas = set(TextVectorizer.extract_meaningful_lemmas(query_text))

        matrix = np.vstack([
            np.frombuffer(r["embedding"], dtype=np.float32)
            if r["embedding"] and len(r["embedding"]) == VECTOR_DIM * 4
            else TextVectorizer.text_to_vector(f"{r['action']} {r['raw_text']}")
            for r in rows
        ])

        cosine_scores = np.dot(matrix, query_vec)

        results = []
        for idx, row in enumerate(rows):
            score = float(cosine_scores[idx])
            row_lemmas = set((row["lemmas"] or "").split())

            common_lemmas = query_lemmas.intersection(row_lemmas)
            if common_lemmas:
                score += 0.30 * (len(common_lemmas) / max(len(query_lemmas), 1))

            if query_text.strip().lower() in (row["action"] or "").lower():
                score += 0.35

            if score >= 0.18:
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
        sort_by: str = "created_desc",
        user_id: int = 1
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT id, user_id, intent, raw_text, action, parsed_date, parsed_time,
                   date_in_past, status, parse_method, created_at
            FROM tasks
            WHERE user_id = ?
        """
        params: List[Any] = [user_id]

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

    def mark_done(self, task_id: int, user_id: int = 1) -> bool:
        """Переключает статус задачи: Active -> Done, а при повторном нажатии Done -> Active."""
        item = self.get_item_by_id(task_id, user_id=user_id)
        if not item:
            return False

        new_status = "Active" if item.get("status") == "Done" else "Done"

        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?",
                (new_status, task_id, user_id)
            )
            conn.commit()
            ok = cur.rowcount > 0

        if ok and self._is_real_db():
            if new_status == "Active" and item.get("parsed_date"):
                CalendarIntegration.remove_event_from_os_calendar(item)
                CalendarIntegration.sync_event_to_os_calendar(item)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200, user_id=user_id))
        return ok

    def delete_item(self, task_id: int, user_id: int = 1) -> bool:
        item_to_remove = self.get_item_by_id(task_id, user_id=user_id)
        if not item_to_remove:
            return False

        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id)
            )
            conn.commit()
            deleted = cur.rowcount > 0

        if deleted and self._is_real_db():
            CalendarIntegration.remove_event_from_os_calendar(item_to_remove)
            CalendarIntegration.export_all_to_ics(self.get_history(limit=200, user_id=user_id))

        return deleted

    def find_and_delete_by_query(
        self,
        query_text: str,
        target_id: Optional[int] = None,
        user_id: int = 1
    ) -> Optional[Dict[str, Any]]:
        target = self.find_best_matching_item(
            query_text=query_text,
            target_id=target_id,
            only_active=False,
            user_id=user_id
        )
        if not target:
            return None
        if self.delete_item(target["id"], user_id=user_id):
            return target
        return None

    def find_and_complete_by_query(
        self,
        query_text: str,
        target_id: Optional[int] = None,
        user_id: int = 1
    ) -> Optional[Dict[str, Any]]:
        target = self.find_best_matching_item(
            query_text=query_text,
            target_id=target_id,
            only_active=True,
            user_id=user_id
        )
        if not target:
            return None
        if self.mark_done(target["id"], user_id=user_id):
            target["status"] = "Done"
            return target
        return None

    def check_and_trigger_upcoming_notifications(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now_dt = now or datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")
        tomorrow_str = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, user_id, intent, raw_text, action, parsed_date, parsed_time, status
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
            if 0 <= diff_seconds <= 3600:
                with self._get_conn() as conn:
                    conn.execute("UPDATE tasks SET notified = 1 WHERE id = ?", (item["id"],))
                    conn.commit()
                if self._is_real_db():
                    CalendarIntegration.send_os_notification(item)
                triggered.append(item)

        return triggered
