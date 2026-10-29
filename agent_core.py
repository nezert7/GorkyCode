import os
import re
import json
import time
import uuid
import logging
import urllib.request
import urllib3
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from openai import OpenAI
from dotenv import load_dotenv

from database import DatabaseManager, get_intent_label_ru, VALID_INTENTS
from tools_schema import build_system_prompt

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(override=True)

logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def format_date_ru(date_str: Optional[str]) -> str:
    """Форматирует YYYY-MM-DD в ДД.ММ.ГГГГ для единого вывода на экран."""
    if not date_str:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return date_str


class RussianDateTimeExtractor:
    """Точное извлечение дат и времени из русской речи (включая числительные словами и дни недели)."""

    WORD_HOURS = {
        "час": 1, "один": 1, "одного": 1, "первого": 1,
        "два": 2, "двух": 2, "второго": 2,
        "три": 3, "трех": 3, "трёх": 3, "третьего": 3,
        "четыре": 4, "четырех": 4, "четырёх": 4, "четвертого": 4, "четвёртого": 4,
        "пять": 5, "пяти": 5, "пятого": 5,
        "шесть": 6, "шести": 6, "шестого": 6,
        "семь": 7, "семи": 7, "седьмого": 7,
        "восемь": 8, "восьми": 8, "восьмого": 8,
        "девять": 9, "девяти": 9, "девятого": 9,
        "десять": 10, "десяти": 10, "десятого": 10,
        "одиннадцать": 11, "одиннадцати": 11, "одиннадцатого": 11,
        "двенадцать": 12, "двенадцати": 12, "двенадцатого": 12,
        "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
        "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
        "девятнадцать": 19, "двадцать": 20, "двадцать один": 21,
        "двадцать два": 22, "двадцать три": 23
    }

    WEEKDAYS_MAP = {
        "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
        "четверг": 3, "пятницу": 4, "пятница": 4,
        "субботу": 5, "суббота": 5, "воскресенье": 6
    }

    MONTHS_MAP = {
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
        "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12
    }

    @classmethod
    def extract_date_and_time(cls, text: str, now: datetime) -> Tuple[Optional[str], Optional[str], str]:
        clean = text
        lower = clean.lower()
        parsed_time: Optional[str] = None
        parsed_date: Optional[str] = None

        tm = re.search(r"(?:(?:\bв|\bна|\bк)\s+)?\b([0-2]?\d)[:.]([0-5]\d)\b", lower)
        if tm:
            h, m = int(tm.group(1)), int(tm.group(2))
            if 0 <= h <= 23:
                if ("вечер" in lower or "дня" in lower) and 1 <= h <= 11:
                    h += 12
                parsed_time = f"{h:02d}:{m:02d}"
                clean = clean[:tm.start()] + " " + clean[tm.end():]
                clean = re.sub(r"\b(?:утра|вечера|дня|ночи)\b", " ", clean, flags=re.IGNORECASE)
                lower = clean.lower()

        if not parsed_time:
            if "полдень" in lower:
                parsed_time = "12:00"
                clean = re.sub(r"\b(?:в|на)?\s*полдень\b", " ", clean, flags=re.IGNORECASE)
            elif "полночь" in lower:
                parsed_time = "00:00"
                clean = re.sub(r"\b(?:в|на)?\s*полночь\b", " ", clean, flags=re.IGNORECASE)
            else:
                half_m = re.search(r"\b(?:в\s+)?половине\s+([а-яё]+)(?:\s+(?:утра|дня|вечера))?", lower)
                if half_m and half_m.group(1) in cls.WORD_HOURS:
                    target_h = cls.WORD_HOURS[half_m.group(1)] - 1
                    if "вечер" in lower or "дня" in lower or (1 <= target_h <= 6):
                        if target_h < 12:
                            target_h += 12
                    parsed_time = f"{target_h:02d}:30"
                    clean = clean[:half_m.start()] + " " + clean[half_m.end():]

        if not parsed_time:
            hm = re.search(
                r"\b(?:в|на|к)\s+([0-2]?\d)\s*(?:час(?:а|ов)?|утра|вечера|дня|ночи)?\b",
                clean.lower()
            )
            if hm:
                h = int(hm.group(1))
                segment = hm.group(0).lower()
                if ("вечер" in segment or "дня" in segment or "вечер" in lower or "дня" in lower) and 1 <= h <= 11:
                    h += 12
                if 0 <= h <= 23:
                    parsed_time = f"{h:02d}:00"
                    clean = clean[:hm.start()] + " " + clean[hm.end():]

        if not parsed_time:
            for word, h_val in sorted(cls.WORD_HOURS.items(), key=lambda x: -len(x[0])):
                pat = rf"\b(?:в|на|к)\s+{word}(?:\s+час(?:а|ов)?)?(?:\s+(утра|дня|вечера|ночи))?\b"
                wm = re.search(pat, clean.lower())
                if wm:
                    h = h_val
                    period = wm.group(1) or ""
                    if (period in ("вечера", "дня") or ("вечер" in clean.lower() or "дня" in clean.lower())) and 1 <= h <= 11:
                        h += 12
                    if 0 <= h <= 23:
                        parsed_time = f"{h:02d}:00"
                        clean = clean[:wm.start()] + " " + clean[wm.end():]
                        break

        lower = clean.lower()

        if re.search(r"\b(?:на\s+)?послезавтра\b", lower):
            parsed_date = (now + timedelta(days=2)).strftime("%Y-%m-%d")
            clean = re.sub(r"\b(?:на\s+)?послезавтра\b", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"\b(?:на\s+)?завтра\b", lower):
            parsed_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            clean = re.sub(r"\b(?:на\s+)?завтра\b", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"\b(?:на\s+)?сегодня\b", lower):
            parsed_date = now.strftime("%Y-%m-%d")
            clean = re.sub(r"\b(?:на\s+)?сегодня\b", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"\b(?:на\s+)?вчера\b", lower):
            parsed_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            clean = re.sub(r"\b(?:на\s+)?вчера\b", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"\bчерез\s+неделю\b", lower):
            parsed_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
            clean = re.sub(r"\bчерез\s+неделю\b", " ", clean, flags=re.IGNORECASE)

        if not parsed_date:
            for day_word, target_wd in cls.WEEKDAYS_MAP.items():
                wd_m = re.search(rf"\b(?:в|во|на)\s+(?:следующ[уюийе]+\s+)?{day_word}\b", clean.lower())
                if wd_m:
                    days_ahead = (target_wd - now.weekday()) % 7
                    if days_ahead == 0:
                        days_ahead = 7
                    parsed_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                    clean = clean[:wd_m.start()] + " " + clean[wd_m.end():]
                    break

        if not parsed_date:
            dm_match = re.search(r"(?:\bна\s+)?\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", clean.lower())
            if dm_match:
                d, m = int(dm_match.group(1)), int(dm_match.group(2))
                y = int(dm_match.group(3)) if dm_match.group(3) else now.year
                try:
                    parsed_date = datetime(y, m, d).strftime("%Y-%m-%d")
                    clean = clean[:dm_match.start()] + " " + clean[dm_match.end():]
                except ValueError:
                    pass
            else:
                month_m = re.search(
                    r"(?:\bна\s+)?\b(\d{1,2})\s+(январ[яе]|феврал[яе]|март[ае]?|апрел[яе]|ма[яе]|июн[яе]|июл[яе]|август[ае]?|сентябр[яе]|октябр[яе]|ноябр[яе]|декабр[яе])\b",
                    clean.lower()
                )
                if month_m:
                    d = int(month_m.group(1))
                    m_prefix = month_m.group(2)[:5]
                    m_num = next((v for k, v in cls.MONTHS_MAP.items() if m_prefix.startswith(k)), now.month)
                    try:
                        parsed_date = datetime(now.year, m_num, d).strftime("%Y-%m-%d")
                        clean = clean[:month_m.start()] + " " + clean[month_m.end():]
                    except ValueError:
                        pass

        clean = re.sub(r"\s+", " ", clean).strip(" ,.-?!")
        return parsed_date, parsed_time, clean


class VoiceUpdateExtractor:
    """Специализированный анализатор команд переноса и изменения задач голосом."""

    RESCHEDULE_PATTERN = re.compile(
        r"^(?:ну\s+|эээ\s+|короче\s+|пожалуйста\s+|ворон[а]?\s+)*"
        r"(?:перенеси|перенести|передвинь|передвинуть|сдвинь|сдвинуть|отложи|отложить|переназначь|переназначить|"
        r"(?:поменяй|измени|обнови|исправь|переставь)\s+(?:время|дату|число|срок))\b\s*(.*)",
        re.IGNORECASE
    )

    EDIT_PATTERN = re.compile(
        r"^(?:ну\s+|эээ\s+|короче\s+|пожалуйста\s+|ворон[а]?\s+)*"
        r"(?:измени|изменить|поменяй|поменять|переименуй|переименовать|исправь|исправить|"
        r"замени|заменить|обнови|обновить|отредактируй|редактировать)\b\s*(.*)",
        re.IGNORECASE
    )

    TYPE_WORDS_STRIP = re.compile(
        r"^(?:мне\s+)?(?:мо[юйе]\s+)?(?:эт[уо]\s+)?"
        r"(?:задачу|задачи|задача|встречу|встречи|встреча|напоминание|напоминания|напоминалку|дело|событие|запись|план)"
        r"(?:\s+(?:про|по|о|об|на\s+тему))?\b\s*",
        re.IGNORECASE
    )

    @classmethod
    def is_update_command(cls, text: str) -> bool:
        clean = text.strip()
        return bool(cls.RESCHEDULE_PATTERN.match(clean) or cls.EDIT_PATTERN.match(clean))

    @classmethod
    def detect_intent_hint(cls, text: str) -> Optional[str]:
        lower = text.lower()
        if any(w in lower for w in ("встреч", "созвон", "обед", "планерк", "планёрк")):
            return "Meeting"
        if any(w in lower for w in ("напоминан", "напоминалк")):
            return "Reminder"
        if "задач" in lower:
            return "Task"
        return None

    @classmethod
    def extract(cls, raw_text: str, now: datetime, llm_parsed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        clean = raw_text.strip()
        intent_hint = cls.detect_intent_hint(clean)

        resched_m = cls.RESCHEDULE_PATTERN.match(clean)
        edit_m = cls.EDIT_PATTERN.match(clean)

        dt_date, dt_time, _ = RussianDateTimeExtractor.extract_date_and_time(clean, now)

        llm_date = (llm_parsed or {}).get("date")
        llm_time = (llm_parsed or {}).get("time")
        final_date = llm_date or dt_date
        final_time = llm_time or dt_time
        target_id = (llm_parsed or {}).get("target_id")

        if resched_m:
            _, _, body_no_dt = RussianDateTimeExtractor.extract_date_and_time(resched_m.group(1), now)
            search_q = cls.TYPE_WORDS_STRIP.sub("", body_no_dt).strip(" ,.-?!")
            search_q = re.sub(r"\b(?:на|в|к)\s*$", "", search_q, flags=re.IGNORECASE).strip(" ,.-?!")
            if not search_q and llm_parsed and llm_parsed.get("search_query"):
                search_q = llm_parsed["search_query"]

            return {
                "operation": "update",
                "target_id": target_id,
                "intent": None,
                "intent_hint": intent_hint,
                "action": None,
                "new_action": None,
                "date": final_date,
                "time": final_time,
                "search_query": search_q or body_no_dt
            }

        body = edit_m.group(1) if edit_m else clean
        _, _, body_no_dt = RussianDateTimeExtractor.extract_date_and_time(body, now)
        body_no_dt = re.sub(r"\b(?:на|в|к)\s*$", "", body_no_dt, flags=re.IGNORECASE).strip(" ,.-?!")

        new_action: Optional[str] = None
        new_intent: Optional[str] = None
        search_q: str = body_no_dt

        split_m = re.split(r"\s+(?:на|в)\s+", body_no_dt, maxsplit=1, flags=re.IGNORECASE)
        if len(split_m) == 2:
            left_part, right_part = split_m[0].strip(), split_m[1].strip()
            search_q = cls.TYPE_WORDS_STRIP.sub("", left_part).strip(" ,.-?!")

            right_lower = right_part.lower()
            if right_lower in ("напоминание", "напоминалку"):
                new_intent = "Reminder"
            elif right_lower in ("встречу", "встреча"):
                new_intent = "Meeting"
            elif right_lower in ("задачу", "задача"):
                new_intent = "Task"
            elif right_part:
                clean_new = cls.TYPE_WORDS_STRIP.sub("", right_part).strip(" ,.-?!")
                if clean_new:
                    new_action = clean_new[0].upper() + clean_new[1:]
        else:
            search_q = cls.TYPE_WORDS_STRIP.sub("", body_no_dt).strip(" ,.-?!")
            llm_new_action = (llm_parsed or {}).get("new_action")
            if llm_new_action and isinstance(llm_new_action, str):
                candidate = llm_new_action.strip()
                if candidate.lower() != search_q.lower() and not cls.is_update_command(candidate):
                    new_action = candidate

        if (llm_parsed or {}).get("search_query") and not search_q:
            search_q = llm_parsed["search_query"]

        return {
            "operation": "update",
            "target_id": target_id,
            "intent": new_intent,
            "intent_hint": intent_hint,
            "action": new_action,
            "new_action": new_action,
            "date": final_date,
            "time": final_time,
            "search_query": search_q
        }


class RegexFallbackParser:
    """Запасной парсер на регулярных выражениях."""

    MEETING_KEYWORDS = ("встреч", "созвон", "обед с", "приём", "прием", "планёрк", "планерк", "стоматолог", "врач")
    REMINDER_KEYWORDS = ("напомни", "напоминан", "напоминалк", "не забыть", "не забудь")
    PARASITE_WORDS = r"(?:^|\s)(ну|эээ|типа|короче|значит так|значит|как его|надо|там|это|вот|поставь|запиши|записать|напоминание|напоминания|напомни мне|напомни|задачу|встречу|событие)(?=\s|$)"

    @classmethod
    def detect_intent(cls, lower_text: str) -> str:
        if any(k in lower_text for k in cls.MEETING_KEYWORDS) and "повестк" not in lower_text:
            return "Meeting"
        if any(k in lower_text for k in cls.REMINDER_KEYWORDS):
            return "Reminder"
        return "Task"

    @classmethod
    def clean_action_text(cls, text: str, now: datetime) -> Optional[str]:
        _, _, clean = RussianDateTimeExtractor.extract_date_and_time(text, now)
        for _ in range(3):
            clean = re.sub(cls.PARASITE_WORDS, " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^(?:на|в|к|про|о)\s+", "", clean.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\b(?:на|в|к)\s*$", "", clean.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" ,.-?!")
        if not clean:
            return None
        return clean[0].upper() + clean[1:]

    @classmethod
    def parse(cls, text: str, now: datetime) -> Optional[Dict[str, Any]]:
        clean = text.strip()
        if len(clean) < 2:
            return None

        lower_text = clean.lower()
        intent = cls.detect_intent(lower_text)
        parsed_date, parsed_time, _ = RussianDateTimeExtractor.extract_date_and_time(clean, now)
        action = cls.clean_action_text(clean, now)

        if not action and not parsed_date and not parsed_time:
            return {"operation": "none", "intent": None, "action": None, "date": None, "time": None}

        is_complete = bool(action and parsed_date and parsed_time)
        return {
            "operation": "create" if is_complete else "clarify",
            "intent": intent,
            "action": action,
            "date": parsed_date,
            "end_date": None,
            "time": parsed_time,
            "search_query": None,
            "question": None
        }


class GigaChatOpenAIAdapter:
    """Быстрая обёртка для работы с GigaChat API с кэшированием токена и клиента."""

    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    def __init__(self, credentials: str, scope: str = "GIGACHAT_API_PERS"):
        clean_creds = re.sub(r"^(Basic|Bearer)\s+", "", credentials.strip(), flags=re.IGNORECASE)
        self.credentials = clean_creds
        self.scope = scope
        self.http_client = httpx.Client(verify=False, timeout=15.0)
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._detected_model: Optional[str] = None
        self._cached_client: Optional[OpenAI] = None

    def _ensure_token(self) -> str:
        now_ts = time.time()
        if self._access_token and now_ts < self._expires_at - 60:
            return self._access_token

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self.credentials}",
        }
        resp = self.http_client.post(
            self.OAUTH_URL,
            headers=headers,
            data={"scope": self.scope}
        )
        if resp.status_code != 200:
            raise RuntimeError(f"GigaChat OAuth error {resp.status_code}: {resp.text}")

        token_data = resp.json()
        self._access_token = token_data["access_token"]
        exp_ms = token_data.get("expires_at", (now_ts + 1800) * 1000)
        self._expires_at = float(exp_ms) / 1000.0
        self._cached_client = OpenAI(
            api_key=self._access_token,
            base_url=self.BASE_URL,
            http_client=self.http_client
        )
        return self._access_token

    def _get_active_model(self, token: str) -> str:
        if self._detected_model:
            return self._detected_model
        try:
            resp = self.http_client.get(
                f"{self.BASE_URL}/models",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                chat_models = [m.get("id") for m in data if "embed" not in (m.get("id") or "").lower()]
                if chat_models:
                    self._detected_model = chat_models[0]
                    return self._detected_model
        except Exception:
            pass
        self._detected_model = "GigaChat"
        return self._detected_model

    @property
    def chat(self):
        token = self._ensure_token()
        active_model = self._get_active_model(token)
        client = self._cached_client or OpenAI(
            api_key=token,
            base_url=self.BASE_URL,
            http_client=self.http_client
        )

        class _ChatWrapper:
            class _Completions:
                def create(self, **kwargs):
                    kwargs["model"] = active_model
                    return client.chat.completions.create(**kwargs)

            def __init__(self):
                self.completions = self._Completions()

        return _ChatWrapper()


class VoronaAgentCore:
    """
    Ядро голосового ассистента «Ворона» с изоляцией данных по аккаунтам пользователей (user_id).
    """

    def __init__(
        self,
        db: DatabaseManager,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.db = db
        self.http_client = self._create_http_client()
        self.providers = self._init_providers(api_key, base_url, model_name)
        self.active_provider_idx = 0

        self.pending_buffer: Dict[str, Dict[str, Any]] = {}
        self.rollback_buffer: Dict[str, Dict[str, Any]] = {}
        self.clarification_buffer: Dict[str, Dict[str, Any]] = {}
        self.fail_streak: Dict[str, int] = {}

    @staticmethod
    def _make_session_key(user_id: int, session_id: str) -> str:
        return f"user_{user_id}_{session_id}"

    @staticmethod
    def _create_http_client() -> httpx.Client:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "HTTP-Referer": "https://localhost:8000",
            "X-Title": "VoronaDesktopAssistant"
        }

        sys_proxies = urllib.request.getproxies()
        proxy_url = (
            os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or sys_proxies.get("https")
            or sys_proxies.get("http")
        )

        if proxy_url:
            if proxy_url.startswith("https://127.0.0.1") or proxy_url.startswith("https://localhost"):
                proxy_url = "http://" + proxy_url[len("https://"):]
            print(f"🌐 [СЕТЬ] Обнаружен системный VPN/прокси: {proxy_url}")
            try:
                return httpx.Client(proxy=proxy_url, headers=headers, timeout=15.0)
            except Exception as e:
                print(f"⚠️ Не удалось подключить прокси ({e}), использую прямое соединение.")

        return httpx.Client(headers=headers, timeout=15.0)

    @staticmethod
    def _discover_groq_model(client: OpenAI) -> str:
        try:
            models_resp = client.models.list()
            available_ids = [m.id for m in models_resp.data]
            chat_models = [
                mid for mid in available_ids
                if not any(skip in mid.lower() for skip in ("whisper", "guard", "tts", "playai", "embed", "allam"))
            ]
            for preferred_keyword in ("llama-3", "llama-4", "qwen", "deepseek", "gemma", "mixtral", "llama"):
                for mid in chat_models:
                    if preferred_keyword in mid.lower():
                        return mid
            if chat_models:
                return chat_models[0]
        except Exception as e:
            print(f"⚠️ Не удалось запросить список моделей Groq ({e})")
        return "llama-3.1-8b-instant"

    @staticmethod
    def _discover_openrouter_model(client: OpenAI) -> str:
        try:
            models_resp = client.models.list()
            free_ids = [m.id for m in models_resp.data if m.id.endswith(":free")]
            for preferred in ("llama-3", "qwen", "gemini", "mistral", "gemma", "deepseek"):
                for mid in free_ids:
                    if preferred in mid.lower():
                        return mid
            if free_ids:
                return free_ids[0]
        except Exception:
            pass
        return "openrouter/free"

    def _init_providers(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        model_name: Optional[str]
    ) -> List[Dict[str, Any]]:
        providers = []

        gigachat_creds = (os.getenv("GIGACHAT_CREDENTIALS") or os.getenv("GIGACHAT_API_KEY") or "").strip()
        gigachat_scope = (os.getenv("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS").strip()

        if gigachat_creds:
            providers.append({
                "name": "GigaChat",
                "client": GigaChatOpenAIAdapter(credentials=gigachat_creds, scope=gigachat_scope),
                "model": "GigaChat"
            })

        if api_key:
            custom_client = OpenAI(
                api_key=api_key,
                base_url=base_url or "https://api.groq.com/openai/v1",
                http_client=self.http_client
            )
            providers.append({
                "name": "Custom Provider",
                "client": custom_client,
                "model": model_name or self._discover_groq_model(custom_client)
            })

        groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
        gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        yandex_key = (os.getenv("YANDEX_API_KEY") or "").strip()
        yandex_folder_id = (os.getenv("YANDEX_FOLDER_ID") or "").strip()

        if yandex_key and yandex_folder_id:
            yandex_http = httpx.Client(timeout=15.0)
            providers.append({
                "name": "YandexGPT (latest)",
                "client": OpenAI(
                    api_key=yandex_key,
                    base_url="https://ai.api.cloud.yandex.net/v1",
                    default_headers={"x-folder-id": yandex_folder_id},
                    http_client=yandex_http
                ),
                "model": f"gpt://{yandex_folder_id}/yandexgpt/latest"
            })

        if groq_key:
            gr_client = OpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                http_client=self.http_client
            )
            groq_model = model_name or self._discover_groq_model(gr_client)
            providers.append({
                "name": f"Groq ({groq_model})",
                "client": gr_client,
                "model": groq_model
            })

        if gemini_key:
            g_client = OpenAI(
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                http_client=self.http_client
            )
            providers.append({
                "name": "Google Gemini (gemini-2.5-flash)",
                "client": g_client,
                "model": model_name or "gemini-2.5-flash"
            })

        if openrouter_key:
            or_client = OpenAI(
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                http_client=self.http_client
            )
            or_model = model_name or self._discover_openrouter_model(or_client)
            providers.append({
                "name": f"OpenRouter ({or_model})",
                "client": or_client,
                "model": or_model
            })

        if openai_key:
            providers.append({
                "name": "OpenAI (gpt-4o-mini)",
                "client": OpenAI(api_key=openai_key, base_url="https://api.openai.com/v1", http_client=self.http_client),
                "model": model_name or "gpt-4o-mini"
            })

        if providers:
            names = ", ".join(p["name"] for p in providers)
            print(f"🔑 [КЛЮЧИ АКТИВНЫ] Подключены провайдеры: {names}\n")
        else:
            print("⚠️ [ВНИМАНИЕ] В .env не найдено ни одного ключа! Работает только аварийный RegEx.\n")
        return providers

    @staticmethod
    def _validate_calendar_date(date_str: Optional[str]) -> Optional[str]:
        if not date_str or not isinstance(date_str, str):
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return None
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
        except ValueError:
            return None

    @staticmethod
    def _validate_time(time_str: Optional[str]) -> Optional[str]:
        if not time_str or not isinstance(time_str, str):
            return None
        if not re.match(r"^[0-2]\d:[0-5]\d$", time_str):
            return None
        h, m = map(int, time_str.split(":"))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return time_str
        return None

    @staticmethod
    def _sanitize_action(action_candidate: Optional[str], now: datetime) -> Optional[str]:
        """Отфильтровывает случайные вопросы LLM или пустые слова дат/времени из названия события."""
        if not action_candidate or not isinstance(action_candidate, str):
            return None
        clean = action_candidate.strip()
        lower = clean.lower()
        # Если LLM случайно записала вопрос в поле action:
        if "?" in clean or any(
            lower.startswith(q) for q in ("уточните", "на какое", "на какую", "какое событие", "когда", "во сколько")
        ):
            return None
        cleaned_by_regex = RegexFallbackParser.clean_action_text(clean, now)
        return cleaned_by_regex

    @staticmethod
    def _build_missing_question(
        action: Optional[str],
        parsed_date: Optional[str],
        parsed_time: Optional[str],
        llm_question: Optional[str] = None
    ) -> str:
        """Формирует понятный вопрос пользователю о том, каких данных не хватает."""
        missing = []
        if not action:
            missing.append("название события")
        if not parsed_date:
            missing.append("дату")
        if not parsed_time:
            missing.append("время")

        known_parts = []
        if action:
            known_parts.append(f"«{action}»")
        if parsed_date:
            known_parts.append(format_date_ru(parsed_date))
        if parsed_time:
            known_parts.append(parsed_time)

        prefix = f"{' '.join(known_parts)}. " if known_parts else ""
        if llm_question and "?" in llm_question:
            return f"{prefix}{llm_question}"

        if len(missing) == 1:
            return f"{prefix}Уточните {missing[0]}."
        elif len(missing) == 2:
            return f"{prefix}Уточните {missing[0]} и {missing[1]}."
        return "Уточните название события, дату и время."

    def _register_failure(self, session_key: str, error_code: str, ui_status: str = "Не поняла") -> Dict[str, Any]:
        logging.error(f"Code {error_code}: Processing failed for session {session_key}")
        self.fail_streak[session_key] = self.fail_streak.get(session_key, 0) + 1
        hint = "Говорите ближе к микрофону" if self.fail_streak[session_key] >= 3 else None
        return {
            "ui_status": ui_status,
            "error_code": error_code,
            "hint": hint,
            "requires_confirmation": False,
            "data": None
        }

    def _call_llm_json(self, raw_text: str, now: datetime, user_id: int = 1) -> Optional[Dict[str, Any]]:
        if not self.providers:
            return None

        active_items = self.db.get_history(limit=20, status_filter="Active", sort_by="date", user_id=user_id)
        sys_prompt = build_system_prompt(now, active_items=active_items)

        for attempt in range(len(self.providers)):
            idx = (self.active_provider_idx + attempt) % len(self.providers)
            provider = self.providers[idx]

            try:
                response = provider["client"].chat.completions.create(
                    model=provider["model"],
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": f"Текст: {raw_text}"}
                    ],
                    temperature=0.0,
                    max_tokens=250
                )
                content = response.choices[0].message.content or ""

                start_idx = content.find("{")
                end_idx = content.rfind("}")
                if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
                    continue

                parsed = json.loads(content[start_idx : end_idx + 1])

                if idx != self.active_provider_idx:
                    print(f"✅ [LLM] Активный провайдер: {provider['name']}")
                    self.active_provider_idx = idx

                return parsed

            except Exception as exc:
                print(f"⚠️ [{provider['name']}] Ошибка: {type(exc).__name__}: {exc}")
                logging.error(f"Code E20/E06: {provider['name']} error ({type(exc).__name__})")
                time.sleep(0.2)
                continue

        return None

    def process_user_input(
        self,
        raw_text: str,
        session_id: str = "default",
        audio_duration_sec: float = 2.0,
        now_override: Optional[datetime] = None,
        auto_confirm: bool = False,
        user_id: int = 1
    ) -> Dict[str, Any]:
        now = now_override or datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        session_key = self._make_session_key(user_id, session_id)

        if audio_duration_sec < 0.5:
            return self._register_failure(session_key, "E02", "Не поняла")

        if not raw_text or len(raw_text.strip()) < 2:
            return self._register_failure(session_key, "E01", "Не поняла")

        clean_input = raw_text.strip()

        # Если фронтенд прислал техническую фразу для сохранения с дефолтами:
        if "по умолчанию" in clean_input.lower() or "оставь как есть" in clean_input.lower():
            staged = self.pending_buffer.get(session_key) or {}
            final_action = (staged.get("action") or "").strip() or "Событие"
            final_date = staged.get("parsed_date") or (now + timedelta(days=1)).strftime("%Y-%m-%d")
            final_time = staged.get("parsed_time") or "11:00"
            final_intent = staged.get("intent") if staged.get("intent") in VALID_INTENTS else "Task"

            self.pending_buffer[session_key] = {
                "user_id": user_id,
                "intent": final_intent,
                "raw_text": staged.get("raw_text") or final_action,
                "action": final_action,
                "parsed_date": final_date,
                "parsed_time": final_time,
                "date_in_past": 1 if final_date < today_str else 0,
                "parse_method": staged.get("parse_method", "llm"),
                "now_override": now
            }
            return {
                "ui_status": "Подтверждение",
                "operation": "create",
                "requires_confirmation": True,
                "data": {
                    "intent": final_intent,
                    "action": final_action,
                    "date": final_date,
                    "time": final_time
                }
            }

        # Проверяем, есть ли предыдущая запись (если пользователь нажал «продолжить» и договорил)
        prev_staged = self.pending_buffer.get(session_key)
        if prev_staged:
            combined_input = f"{prev_staged.get('raw_text', '')}. {clean_input}".strip(" .")
        else:
            combined_input = clean_input

        # Локально извлекаем дату, время и текст из новой реплики (страховка для LLM)
        dt_date_new, dt_time_new, _ = RussianDateTimeExtractor.extract_date_and_time(clean_input, now)
        action_from_new = RegexFallbackParser.clean_action_text(clean_input, now)

        parse_method = "llm"
        parsed_data = self._call_llm_json(combined_input, now, user_id=user_id)

        if not isinstance(parsed_data, dict) or "operation" not in parsed_data:
            parse_method = "regex"
            parsed_data = RegexFallbackParser.parse(combined_input, now)
            if not parsed_data:
                return self._register_failure(session_key, "E07", "Не поняла формат")

        operation = parsed_data.get("operation")

        # Если мы НЕ в режиме дозаписи черновика, поддерживаем стандартные команды управления базой
        if not prev_staged:
            if VoiceUpdateExtractor.is_update_command(clean_input) or operation == "update":
                parsed_data = VoiceUpdateExtractor.extract(clean_input, now, llm_parsed=parsed_data)
                operation = "update"

            if operation == "list_period":
                start_d = self._validate_calendar_date(parsed_data.get("date")) or today_str
                end_d = self._validate_calendar_date(parsed_data.get("end_date")) or start_d
                intent_filter = parsed_data.get("intent")
                items = self.db.get_items_by_period(start_d, end_d, intent_filter, user_id=user_id)
                return {
                    "ui_status": "Список событий",
                    "operation": "list_period",
                    "requires_confirmation": False,
                    "period": {"start": start_d, "end": end_d},
                    "intent_filter": intent_filter,
                    "items": items
                }

            if operation == "search":
                query = parsed_data.get("search_query") or parsed_data.get("action") or clean_input
                found = self.db.search_past_items(query, user_id=user_id)
                return {
                    "ui_status": "Результаты поиска",
                    "operation": "search",
                    "requires_confirmation": False,
                    "search_query": query,
                    "items": found
                }

            if operation == "delete":
                query = parsed_data.get("search_query") or parsed_data.get("action") or clean_input
                deleted_item = self.db.find_and_delete_by_query(
                    query, target_id=parsed_data.get("target_id"), user_id=user_id
                )
                return {
                    "ui_status": "Удалено" if deleted_item else "Не найдено",
                    "operation": "delete",
                    "requires_confirmation": False,
                    "search_query": query,
                    "deleted": deleted_item
                }

            if operation == "complete":
                query = parsed_data.get("search_query") or parsed_data.get("action") or clean_input
                completed_item = self.db.find_and_complete_by_query(
                    query, target_id=parsed_data.get("target_id"), user_id=user_id
                )
                return {
                    "ui_status": "Выполнено" if completed_item else "Не найдено",
                    "operation": "complete",
                    "requires_confirmation": False,
                    "search_query": query,
                    "completed": completed_item
                }

            if operation == "update":
                query = parsed_data.get("search_query") or clean_input
                target_id = parsed_data.get("target_id")
                intent_hint = parsed_data.get("intent_hint")
                new_action = parsed_data.get("new_action") or parsed_data.get("action")
                new_date = self._validate_calendar_date(parsed_data.get("date"))
                new_time = self._validate_time(parsed_data.get("time"))
                new_intent = parsed_data.get("intent") if parsed_data.get("intent") in VALID_INTENTS else None

                target_item = self.db.find_best_matching_item(
                    query_text=query, target_id=target_id, intent_hint=intent_hint, only_active=True, user_id=user_id
                )
                if not target_item:
                    return {
                        "ui_status": "Не найдено",
                        "operation": "update",
                        "requires_confirmation": False,
                        "search_query": query,
                        "updated": None
                    }
                updated_item = self.db.update_item(
                    task_id=target_item["id"],
                    action=new_action if new_action else None,
                    parsed_date=new_date if new_date is not None else "__UNSET__",
                    parsed_time=new_time if new_time is not None else "__UNSET__",
                    intent=new_intent,
                    user_id=user_id
                )
                return {
                    "ui_status": "Обновлено" if updated_item else "Не найдено",
                    "operation": "update",
                    "requires_confirmation": False,
                    "search_query": query,
                    "old_item": target_item,
                    "updated": updated_item
                }

        # Собираем поля события из ответа LLM + локального парсера + предыдущей записи (если это дозапись)
        llm_action = self._sanitize_action(parsed_data.get("action"), now)
        llm_date = self._validate_calendar_date(parsed_data.get("date"))
        llm_time = self._validate_time(parsed_data.get("time"))
        llm_intent = parsed_data.get("intent") if parsed_data.get("intent") in VALID_INTENTS else None

        # Если пользователь не называл дату ни в первой, ни во второй записи, не даём LLM выдумать сегодняшнюю дату
        dt_date_combined, _, _ = RussianDateTimeExtractor.extract_date_and_time(combined_input, now)
        has_any_date_word = bool(
            dt_date_combined
            or any(w in combined_input.lower() for w in ("сегодня", "завтра", "послезавтра", "недел", "числ", "месяц"))
        )
        if not has_any_date_word and not (prev_staged and prev_staged.get("parsed_date")):
            llm_date = None

        if prev_staged:
            # При дозаписи: обновляем дату/время новыми значениями, а название сохраняем или дополняем
            validated_date = dt_date_new or llm_date or prev_staged.get("parsed_date")
            validated_time = dt_time_new or llm_time or prev_staged.get("parsed_time")
            action = prev_staged.get("action") or llm_action or action_from_new
            intent = prev_staged.get("intent") or llm_intent or RegexFallbackParser.detect_intent(combined_input.lower())
        else:
            validated_date = llm_date or dt_date_new
            validated_time = llm_time or dt_time_new
            action = llm_action or action_from_new
            intent = llm_intent or RegexFallbackParser.detect_intent(combined_input.lower())

        if intent == "Task" and any(k in combined_input.lower() for k in RegexFallbackParser.REMINDER_KEYWORDS):
            intent = "Reminder"

        if not action and not validated_date and not validated_time:
            return self._register_failure(session_key, "E03_E04", "Не поняла")

        self.fail_streak[session_key] = 0
        date_in_past = 1 if (validated_date and validated_date < today_str) else 0

        # Сохраняем черновик в буфер ожидания (в БД и Календарь ничего НЕ пишется до кнопки «сохранить»!)
        staged_record = {
            "user_id": user_id,
            "intent": intent,
            "raw_text": combined_input,
            "action": action,
            "parsed_date": validated_date,
            "parsed_time": validated_time,
            "date_in_past": date_in_past,
            "parse_method": parse_method,
            "now_override": now
        }
        self.pending_buffer[session_key] = staged_record

        # Проверяем, все ли 3 элемента (название, дата, время) заполнены
        is_complete = bool(action and validated_date and validated_time)

        if not is_complete:
            question = self._build_missing_question(
                action=action,
                parsed_date=validated_date,
                parsed_time=validated_time,
                llm_question=parsed_data.get("question")
            )
            self.clarification_buffer[session_key] = {
                "original_text": combined_input,
                "partial_data": staged_record
            }
            return {
                "ui_status": "Уточнение",
                "operation": "clarify",
                "requires_confirmation": True,
                "question": question,
                "data": {
                    "intent": intent,
                    "action": action,
                    "date": validated_date,
                    "time": validated_time
                }
            }

        self.clarification_buffer.pop(session_key, None)

        if auto_confirm:
            return self.confirm_pending(session_id=session_id, user_id=user_id)

        return {
            "ui_status": "Подтверждение",
            "operation": "create",
            "requires_confirmation": True,
            "data": {
                "intent": intent,
                "raw_text": combined_input,
                "action": action,
                "date": validated_date,
                "time": validated_time,
                "date_in_past": date_in_past,
                "parse_method": parse_method
            }
        }

    def confirm_pending(self, session_id: str = "default", user_id: int = 1) -> Dict[str, Any]:
        """
        Вызывается ТОЛЬКО при нажатии на кнопку «сохранить».
        Если каких-то данных нет, заполняет их базовыми значениями по умолчанию:
        время - 11:00, дата - завтра, название - Событие.
        """
        session_key = self._make_session_key(user_id, session_id)
        self.rollback_buffer.pop(session_key, None)
        staged = self.pending_buffer.get(session_key)
        if not staged:
            clar_draft = self.clarification_buffer.get(session_key) or {}
            staged = clar_draft.get("partial_data")

        if not staged:
            return {"ui_status": "Готова", "operation": "noop", "requires_confirmation": False, "saved": None}

        now = staged.get("now_override") or datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Базовые значения по умолчанию для незаполненных полей
        final_action = (staged.get("action") or "").strip() or "Событие"
        final_date = staged.get("parsed_date") or (now + timedelta(days=1)).strftime("%Y-%m-%d")
        final_time = staged.get("parsed_time") or "11:00"
        final_intent = staged.get("intent") if staged.get("intent") in VALID_INTENTS else "Task"
        date_in_past = 1 if final_date < today_str else 0

        try:
            saved_item = self.db.save_confirmed_item(
                intent=final_intent,
                raw_text=staged.get("raw_text") or final_action,
                action=final_action,
                parsed_date=final_date,
                parsed_time=final_time,
                date_in_past=date_in_past,
                parse_method=staged.get("parse_method", "llm"),
                now_override=now,
                user_id=user_id
            )
            self.pending_buffer.pop(session_key, None)
            self.clarification_buffer.pop(session_key, None)
            return {
                "ui_status": "Зафиксировано",
                "operation": "create",
                "requires_confirmation": False,
                "saved": saved_item
            }
        except Exception as exc:
            logging.error(f"Code E22: Database write failed ({type(exc).__name__}: {exc})")
            return {
                "ui_status": "Ошибка записи",
                "error_code": "E22",
                "can_retry": True,
                "saved": None
            }

    def cancel_pending(self, session_id: str = "default", user_id: int = 1) -> Dict[str, Any]:
        """Стирает всё, что было введено, без сохранения в БД и календарь."""
        session_key = self._make_session_key(user_id, session_id)
        self.pending_buffer.pop(session_key, None)
        self.clarification_buffer.pop(session_key, None)
        self.rollback_buffer.pop(session_key, None)
        return {
            "ui_status": "Готова",
            "operation": "cancel",
            "requires_confirmation": False
        }


_default_db: Optional[DatabaseManager] = None
_default_agent: Optional[VoronaAgentCore] = None


def get_shared_agent() -> VoronaAgentCore:
    global _default_db, _default_agent
    if _default_agent is None:
        _default_db = DatabaseManager(db_path="events.db")
        _default_agent = VoronaAgentCore(db=_default_db)
    return _default_agent


def format_spoken_response(result: Dict[str, Any]) -> str:
    """
    Форматирует вывод на экран:
    - Если запрос неполный (clarify): выводит вопрос о недостающих полях.
    - Если данные собраны (Подтверждение / Зафиксировано): выводит СТРОГО единый формат
      «ДД.ММ.ГГГГ ЧЧ:ММ — Название события» без лишних слов.
    """
    ui_status = result.get("ui_status", "")
    operation = result.get("operation", "")

    if ui_status in ("Не поняла", "Не поняла формат"):
        msg = "Извините, я не совсем поняла запрос. Повторите, пожалуйста."
        if result.get("hint"):
            msg += f" {result['hint']}."
        return msg

    if ui_status == "Уточнение" or operation == "clarify":
        return result.get("question") or "Уточните дату, время или название события."

    if ui_status == "Подтверждение":
        data = result.get("data") or {}
        d_str = format_date_ru(data.get("date"))
        t_str = data.get("time") or ""
        act_str = data.get("action") or ""
        return f"{d_str} {t_str} — {act_str}".strip(" —")

    if ui_status == "Зафиксировано":
        saved = result.get("saved") or {}
        d_str = format_date_ru(saved.get("parsed_date"))
        t_str = saved.get("parsed_time") or ""
        act_str = saved.get("action") or ""
        return f"{d_str} {t_str} — {act_str}".strip(" —")

    if operation == "delete":
        deleted = result.get("deleted")
        if deleted:
            return f"Удалено: {deleted['action']}"
        return "Запись для удаления не найдена."

    if operation == "complete":
        completed = result.get("completed")
        if completed:
            return f"Выполнено: {completed['action']}"
        return "Активная запись не найдена."

    if operation == "update":
        updated = result.get("updated")
        if updated:
            d_str = format_date_ru(updated.get("parsed_date"))
            t_str = updated.get("parsed_time") or ""
            return f"{d_str} {t_str} — {updated.get('action', '')}".strip(" —")
        return "Запись для изменения не найдена."

    if ui_status == "Готова" and operation == "cancel":
        return "Запись отменена."

    return "Готова!"


def run_agent_turn(
    user_query: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: str = "default",
    audio_duration_sec: float = 2.0,
    user_id: int = 1
) -> Dict[str, Any]:
    agent = get_shared_agent()
    res = agent.process_user_input(
        raw_text=user_query,
        session_id=session_id,
        audio_duration_sec=audio_duration_sec,
        auto_confirm=False,
        user_id=user_id
    )
    res["spoken_response"] = format_spoken_response(res)
    return res


def run_agent_loop(user_query: str, history: Optional[List[Dict[str, str]]] = None, user_id: int = 1) -> str:
    turn_result = run_agent_turn(user_query=user_query, history=history, user_id=user_id)
    return turn_result["spoken_response"]