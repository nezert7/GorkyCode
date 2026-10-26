import sqlite3
import re
import hashlib
import numpy as np
import pymorphy3
from datetime import datetime
from typing import Optional, List, Dict, Any

# Инициализируем морфологический анализатор русского языка (загружается 1 раз в ОЗУ)
morph = pymorphy3.MorphAnalyzer()

VECTOR_DIM = 512  # Размерность вектора NumPy для семантического поиска


class TextVectorizer:
    """
    Превращает любой русский текст в нормализованные леммы и 512-мерный вектор NumPy (float32).
    Устойчив к падежам, однокоренным словам и опечаткам распознавания речи (например, 'малако', 'кли ентом').
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

        # 1. Добавляем вес целым леммам (вес 2.0)
        for lemma in lemmas_str.split():
            idx = int(hashlib.md5(lemma.encode("utf-8")).hexdigest(), 16) % VECTOR_DIM
            vec[idx] += 2.0

        # 2. Добавляем вес символьным 3-граммам (улавливает однокоренные слова и опечатки STT, вес 1.0)
        for i in range(len(combined) - 2):
            trigram = combined[i : i + 3]
            idx = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16) % VECTOR_DIM
            vec[idx] += 1.0

        # Нормализуем вектор по длине (L2-норма), чтобы скалярное произведение сразу давало косинус угла
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


class DatabaseManager:
    """
    Слой хранения данных SQLite + Поиск на NumPy.
    Полностью реализует схему таблицы tasks от Аналитика и 4 сценария ТЗ.
    """

    def __init__(self, db_path: str = "events.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Создает таблицу tasks и индексы строго по контракту Аналитика + поля для поиска."""
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
        """
        Сохраняет подтвержденную запись в таблицу tasks.
        Автоматически генерирует леммы и NumPy-вектор для последующего поиска.
        """
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

        return {
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

    def check_meeting_conflict(self, parsed_date: str, parsed_time: str) -> List[Dict[str, Any]]:
        """Дополнительная возможность из ТЗ: проверка конфликтующих встреч на то же время."""
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
        intent_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Сценарий №3 из ТЗ: Получение информации о предстоящих событиях за период
        ('Что у меня сегодня?', 'Какие задачи на завтра?', 'Что запланировано на эту неделю?').
        """
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

        query += " ORDER BY parsed_date ASC, COALESCE(parsed_time, '23:59') ASC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def search_past_items(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Сценарий №4 из ТЗ: Поиск старых задач и событий по естественному запросу.
        Использует матричное косинусное сходство на NumPy + пересечение лемм pymorphy3.
        """
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()

        if not rows or not query_text.strip():
            return []

        query_vec = TextVectorizer.text_to_vector(query_text)
        query_lemmas = set(TextVectorizer.extract_lemmas(query_text).split())

        # Распаковываем бинарные векторы из SQLite в 2D-матрицу NumPy (N, 512)
        matrix = np.vstack([
            np.frombuffer(r["embedding"], dtype=np.float32) if r["embedding"]
            else np.zeros(VECTOR_DIM, dtype=np.float32)
            for r in rows
        ])

        # Матричное умножение: так как векторы уже L2-нормализованы, dot product = Cosine Similarity
        cosine_scores = np.dot(matrix, query_vec)

        results = []
        for idx, row in enumerate(rows):
            score = float(cosine_scores[idx])
            row_lemmas = set((row["lemmas"] or "").split())

            # Бонус за совпадение начальных форм слов (лемм)
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

    def get_history(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Сценарий 6 из документа команды: История запросов (новые сверху)."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, intent, raw_text, action, parsed_date, parsed_time,
                       date_in_past, status, parse_method, created_at
                FROM tasks
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
            return [dict(r) for r in rows]

    def mark_done(self, task_id: int) -> bool:
        """Переводит задачу в статус Done."""
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE tasks SET status = 'Done' WHERE id = ?", (task_id,))
            conn.commit()
            return cur.rowcount > 0