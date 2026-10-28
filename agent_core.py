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
from typing import Optional, Dict, Any, List
from openai import OpenAI
from dotenv import load_dotenv

from database import DatabaseManager
from tools_schema import build_system_prompt

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(override=True)

logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


class RegexFallbackParser:
    """
    Запасной парсер на регулярных выражениях (по спецификации Аналитика, код E06).
    Поддерживает create, list_period, search, delete, complete и clarify.
    """

    MEETING_KEYWORDS = ("встреч", "созвон", "обед с", "приём", "прием", "планёрк", "планерк")
    PARASITE_WORDS = r"(?:^|\s)(ну|эээ|типа|короче|значит так|значит|как его|надо|там|это|вот)(?=\s|$)"

    @classmethod
    def parse(cls, text: str, now: datetime) -> Optional[Dict[str, Any]]:
        clean = text.strip()
        if len(clean) < 2:
            return None

        lower_text = clean.lower()

        # 1. Удаление голосом
        del_match = re.search(r"^(?:удали|удалить|убери|убрать|отмени|отменить|сотри)\s+(.+)", lower_text)
        if del_match:
            q = re.sub(r"\b(задачу|встречу|напоминание|дело|про|по)\b", "", del_match.group(1)).strip(" ,.?!")
            return {
                "operation": "delete",
                "intent": None,
                "action": None,
                "date": None,
                "end_date": None,
                "time": None,
                "search_query": q or del_match.group(1)
            }

        # 2. Отметка задачи выполненной голосом
        done_match = re.search(
            r"(?:отметь|отметить|заверши|завершить|выполнил[а]?|сделал[а]?|закрой|закрыть)\s+(.+)",
            lower_text
        )
        if done_match or "выполненной" in lower_text or "выполнено" in lower_text:
            q = re.sub(
                r"\b(отметь|отметить|заверши|задачу|встречу|дело|как|выполненной|выполненную|выполнено|сделанной|про|по)\b",
                "",
                lower_text
            ).strip(" ,.?!")
            return {
                "operation": "complete",
                "intent": None,
                "action": None,
                "date": None,
                "end_date": None,
                "time": None,
                "search_query": q or clean
            }

        # 3. Поиск старых задач
        search_match = re.search(r"(?:найди|найти|поищи|искать|когда\s+у\s+меня\s+был[аои]?)\s+(.+)", lower_text)
        if search_match or "найди ее" in lower_text or "найди её" in lower_text:
            q = re.sub(r"\b(задачу|встречу|про|по|я когда-то ставил|найди ее|найди её)\b", "", lower_text).strip(" ,.?!")
            return {
                "operation": "search",
                "intent": None,
                "action": None,
                "date": None,
                "end_date": None,
                "time": None,
                "search_query": q or clean
            }

        # 4. Просмотр задач за период
        if re.search(r"\b(что у меня|какие дела|какие задачи|какие встречи|какие планы|есть ли встречи|что запланировано|покажи задачи|покажи встречи)\b", lower_text):
            start_date = now.strftime("%Y-%m-%d")
            end_date = start_date
            if "завтра" in lower_text:
                start_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                end_date = start_date
            elif "недел" in lower_text:
                days_until_sunday = 6 - now.weekday()
                end_date = (now + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")

            intent_filter = None
            if "встреч" in lower_text:
                intent_filter = "Meeting"
            elif "задач" in lower_text:
                intent_filter = "Task"

            return {
                "operation": "list_period",
                "intent": intent_filter,
                "action": None,
                "date": start_date,
                "end_date": end_date,
                "time": None,
                "search_query": None
            }

        intent = "Task"
        if any(k in lower_text for k in cls.MEETING_KEYWORDS) and "повестк" not in lower_text:
            intent = "Meeting"

        parsed_time = None
        time_match = re.search(r"\b([0-2]?\d):([0-5]\d)\b", lower_text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            if 0 <= h <= 23:
                parsed_time = f"{h:02d}:{m:02d}"
                clean = clean[:time_match.start()] + clean[time_match.end():]
        else:
            hour_match = re.search(r"\bв\s+([0-2]?\d)\s+час(?:а|ов)?\b", lower_text)
            if hour_match:
                h = int(hour_match.group(1))
                if 0 <= h <= 23:
                    parsed_time = f"{h:02d}:00"
                    clean = re.sub(r"\bв\s+[0-2]?\d\s+час(?:а|ов)?\b", "", clean, flags=re.IGNORECASE)

        parsed_date = None
        if re.search(r"(?:^|\s)послезавтра(?=\s|$)", lower_text):
            parsed_date = (now + timedelta(days=2)).strftime("%Y-%m-%d")
            clean = re.sub(r"(?:^|\s)послезавтра(?=\s|$)", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"(?:^|\s)завтра(?=\s|$)", lower_text):
            parsed_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            clean = re.sub(r"(?:^|\s)завтра(?=\s|$)", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"(?:^|\s)сегодня(?=\s|$)", lower_text):
            parsed_date = now.strftime("%Y-%m-%d")
            clean = re.sub(r"(?:^|\s)сегодня(?=\s|$)", " ", clean, flags=re.IGNORECASE)
        elif re.search(r"(?:^|\s)вчера(?=\s|$)", lower_text):
            parsed_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            clean = re.sub(r"(?:^|\s)вчера(?=\s|$)", " ", clean, flags=re.IGNORECASE)
        else:
            dm_match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", lower_text)
            if dm_match:
                d, m = int(dm_match.group(1)), int(dm_match.group(2))
                y = int(dm_match.group(3)) if dm_match.group(3) else now.year
                try:
                    dt = datetime(y, m, d)
                    parsed_date = dt.strftime("%Y-%m-%d")
                    clean = clean[:dm_match.start()] + clean[dm_match.end():]
                except ValueError:
                    parsed_date = None

        for _ in range(3):
            clean = re.sub(cls.PARASITE_WORDS, " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" ,.-?!")

        if not clean:
            return {"operation": "none", "intent": None, "action": None, "date": None, "time": None}

        action = clean[0].upper() + clean[1:]
        return {
            "operation": "create",
            "intent": intent,
            "action": action,
            "date": parsed_date,
            "end_date": None,
            "time": parsed_time,
            "search_query": None
        }


class GigaChatOpenAIAdapter:
    """Обёртка для работы с GigaChat API с автоматическим определением доступной модели."""

    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    def __init__(self, credentials: str, scope: str = "GIGACHAT_API_PERS"):
        clean_creds = re.sub(r"^(Basic|Bearer)\s+", "", credentials.strip(), flags=re.IGNORECASE)
        self.credentials = clean_creds
        self.scope = scope
        self.http_client = httpx.Client(verify=False, timeout=20.0)
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._detected_model: Optional[str] = None

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
        http_client = self.http_client
        base_url = self.BASE_URL

        class _ChatWrapper:
            class _Completions:
                def create(self, **kwargs):
                    kwargs["model"] = active_model
                    client = OpenAI(api_key=token, base_url=base_url, http_client=http_client)
                    return client.chat.completions.create(**kwargs)

            def __init__(self):
                self.completions = self._Completions()

        return _ChatWrapper()


class VoronaAgentCore:
    """
    Ядро голосового ассистента «Ворона».
    Реализует создание, поиск за период, векторный поиск, голосовое удаление,
    отметку выполнения и многошаговый уточняющий диалог.
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
        self.clarification_buffer: Dict[str, Dict[str, Any]] = {}
        self.fail_streak: Dict[str, int] = {}

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
        gigachat_creds = (os.getenv("GIGACHAT_CREDENTIALS") or os.getenv("GIGACHAT_API_KEY") or "").strip()
        gigachat_scope = (os.getenv("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS").strip()

        if gigachat_creds:
            providers.append({
                "name": "GigaChat",
                "client": GigaChatOpenAIAdapter(credentials=gigachat_creds, scope=gigachat_scope),
                "model": "GigaChat"
            })

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
    def _apply_analyst_rules(
        raw_text: str,
        validated_date: Optional[str],
        validated_time: Optional[str],
        now: datetime
    ) -> Optional[str]:
        lower_text = raw_text.lower()
        today_str = now.strftime("%Y-%m-%d")
        now_time_str = now.strftime("%H:%M")

        weekdays_map = {
            "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
            "четверг": 3, "пятницу": 4, "пятница": 4,
            "субботу": 5, "суббота": 5, "воскресенье": 6
        }
        correction_match = re.search(
            r"в\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)"
            r"[\s,]*(?:а\s+)?нет\s+в\s+"
            r"(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)",
            lower_text
        )
        if correction_match:
            target_day_name = correction_match.group(2)
            target_wd = weekdays_map[target_day_name]
            days_ahead = (target_wd - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        explicit_today_words = ("сегодня", "завтра", "послезавтра", "вчера")
        has_explicit_day = any(w in lower_text for w in explicit_today_words) or any(
            w in lower_text for w in weekdays_map
        )
        if (
            validated_time
            and (validated_date is None or validated_date == today_str)
            and not has_explicit_day
        ):
            if validated_time <= now_time_str:
                return (now + timedelta(days=1)).strftime("%Y-%m-%d")
            return today_str

        return validated_date

    def _register_failure(self, session_id: str, error_code: str, ui_status: str = "Не поняла") -> Dict[str, Any]:
        logging.error(f"Code {error_code}: Processing failed for session {session_id}")
        self.fail_streak[session_id] = self.fail_streak.get(session_id, 0) + 1
        hint = "Говорите ближе к микрофону" if self.fail_streak[session_id] >= 3 else None
        return {
            "ui_status": ui_status,
            "error_code": error_code,
            "hint": hint,
            "requires_confirmation": False,
            "data": None
        }

    def _call_llm_json(self, raw_text: str, now: datetime) -> Optional[Dict[str, Any]]:
        if not self.providers:
            return None

        sys_prompt = build_system_prompt(now)

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
                    max_tokens=220
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
                time.sleep(0.3)
                continue

        return None

    def process_user_input(
        self,
        raw_text: str,
        session_id: str = "default",
        audio_duration_sec: float = 2.0,
        now_override: Optional[datetime] = None,
        auto_confirm: bool = False
    ) -> Dict[str, Any]:
        now = now_override or datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if audio_duration_sec < 0.5:
            return self._register_failure(session_id, "E02", "Не поняла")

        if not raw_text or len(raw_text.strip()) < 2:
            return self._register_failure(session_id, "E01", "Не поняла")

        clean_input = raw_text.strip()

        # Если сессия ожидает ответа на уточняющий вопрос — объединяем предыдущий черновик с новым ответом
        if session_id in self.clarification_buffer:
            prev_draft = self.clarification_buffer.pop(session_id)
            clean_input = f"{prev_draft.get('original_text', '')} {clean_input}".strip()

        parse_method = "llm"
        parsed_data = self._call_llm_json(clean_input, now)

        if not isinstance(parsed_data, dict) or "operation" not in parsed_data:
            parse_method = "regex"
            parsed_data = RegexFallbackParser.parse(clean_input, now)
            if not parsed_data:
                return self._register_failure(session_id, "E07", "Не поняла формат")

        operation = parsed_data.get("operation")

        if operation == "none" or (operation == "create" and not parsed_data.get("action")):
            return self._register_failure(session_id, "E03_E04", "Не поняла")

        self.fail_streak[session_id] = 0

        # Сценарий: Поиск задач за определенный период (+ фильтр по типу)
        if operation == "list_period":
            start_d = self._validate_calendar_date(parsed_data.get("date")) or today_str
            end_d = self._validate_calendar_date(parsed_data.get("end_date")) or start_d
            intent_filter = parsed_data.get("intent")
            items = self.db.get_items_by_period(start_d, end_d, intent_filter)
            return {
                "ui_status": "Список событий",
                "operation": "list_period",
                "requires_confirmation": False,
                "period": {"start": start_d, "end": end_d},
                "intent_filter": intent_filter,
                "items": items
            }

        # Сценарий: Семантический поиск прошлых задач
        if operation == "search":
            query = parsed_data.get("search_query") or parsed_data.get("action") or clean_input
            found = self.db.search_past_items(query)
            return {
                "ui_status": "Результаты поиска",
                "operation": "search",
                "requires_confirmation": False,
                "search_query": query,
                "items": found
            }

        # Сценарий: Голосовое удаление задачи
        if operation == "delete":
            query = parsed_data.get("search_query") or parsed_data.get("action") or clean_input
            deleted_item = self.db.find_and_delete_by_query(query)
            return {
                "ui_status": "Удалено" if deleted_item else "Не найдено",
                "operation": "delete",
                "requires_confirmation": False,
                "search_query": query,
                "deleted": deleted_item
            }

        # Сценарий: Голосовая отметка задачи выполненной
        if operation == "complete":
            query = parsed_data.get("search_query") or parsed_data.get("action") or clean_input
            completed_item = self.db.find_and_complete_by_query(query)
            return {
                "ui_status": "Выполнено" if completed_item else "Не найдено",
                "operation": "complete",
                "requires_confirmation": False,
                "search_query": query,
                "completed": completed_item
            }

        # Сценарий: Неоднозначный запрос и уточняющий диалог
        if operation == "clarify":
            question = parsed_data.get("action") or "Уточните, пожалуйста, дату или время."
            self.clarification_buffer[session_id] = {
                "original_text": clean_input,
                "partial_data": parsed_data
            }
            return {
                "ui_status": "Уточнение",
                "operation": "clarify",
                "requires_confirmation": False,
                "question": question
            }

        intent = parsed_data.get("intent")
        if intent not in ("Task", "Meeting"):
            intent = "Task"

        action = (parsed_data.get("action") or "").strip()
        if not action:
            return self._register_failure(session_id, "E04", "Не поняла")

        raw_date = parsed_data.get("date")
        validated_date = self._validate_calendar_date(raw_date)
        date_warning = None
        if raw_date is not None and validated_date is None:
            logging.error("Code E10: Invalid calendar date reset to NULL")
            date_warning = "Дата не распознана"

        validated_time = self._validate_time(parsed_data.get("time"))

        validated_date = self._apply_analyst_rules(
            raw_text=clean_input,
            validated_date=validated_date,
            validated_time=validated_time,
            now=now
        )

        date_in_past = 0
        if validated_date and validated_date < today_str:
            date_in_past = 1

        conflicts = []
        if intent == "Meeting" and validated_date and validated_time:
            conflicts = self.db.check_meeting_conflict(validated_date, validated_time)

        staged_record = {
            "intent": intent,
            "raw_text": clean_input,
            "action": action,
            "parsed_date": validated_date,
            "parsed_time": validated_time,
            "date_in_past": date_in_past,
            "parse_method": parse_method,
            "date_warning": date_warning,
            "conflicts": conflicts,
            "now_override": now
        }

        self.pending_buffer[session_id] = staged_record

        if auto_confirm:
            return self.confirm_pending(session_id)

        return {
            "ui_status": "Подтверждение",
            "operation": "create",
            "requires_confirmation": True,
            "data": {
                "intent": intent,
                "raw_text": clean_input,
                "action": action,
                "date": validated_date,
                "time": validated_time,
                "date_in_past": date_in_past,
                "parse_method": parse_method,
                "date_warning": date_warning,
                "conflicts": conflicts
            }
        }

    def confirm_pending(self, session_id: str = "default") -> Dict[str, Any]:
        staged = self.pending_buffer.get(session_id)
        if not staged:
            return {"ui_status": "Ошибка", "error_code": "NO_PENDING", "saved": None}

        try:
            saved_item = self.db.save_confirmed_item(
                intent=staged["intent"],
                raw_text=staged["raw_text"],
                action=staged["action"],
                parsed_date=staged["parsed_date"],
                parsed_time=staged["parsed_time"],
                date_in_past=staged["date_in_past"],
                parse_method=staged["parse_method"],
                now_override=staged.get("now_override")
            )
            self.pending_buffer.pop(session_id, None)
            return {
                "ui_status": "Зафиксировано",
                "operation": "create",
                "requires_confirmation": False,
                "saved": saved_item
            }
        except Exception as exc:
            logging.error(f"Code E22: Database write failed ({type(exc).__name__})")
            return {
                "ui_status": "Ошибка записи",
                "error_code": "E22",
                "can_retry": True,
                "saved": None
            }

    def cancel_pending(self, session_id: str = "default") -> Dict[str, Any]:
        self.pending_buffer.pop(session_id, None)
        self.clarification_buffer.pop(session_id, None)
        return {
            "ui_status": "Готова",
            "operation": "cancel",
            "requires_confirmation": False
        }


# =====================================================================
# МОСТ ИНТЕГРАЦИИ С MAIN.PY И VOICE_SERVICE.PY
# =====================================================================

_default_db: Optional[DatabaseManager] = None
_default_agent: Optional[VoronaAgentCore] = None

CONFIRM_WORDS = {"да", "верно", "подтверждаю", "сохрани", "сохранить", "ок", "окей", "ага", "правильно", "точно"}
CANCEL_WORDS = {"нет", "неверно", "отмена", "отменить", "сброс", "не надо"}


def get_shared_agent() -> VoronaAgentCore:
    global _default_db, _default_agent
    if _default_agent is None:
        _default_db = DatabaseManager(db_path="events.db")
        _default_agent = VoronaAgentCore(db=_default_db)
    return _default_agent


def format_spoken_response(result: Dict[str, Any]) -> str:
    """Формирует естественный голосовой ответ на русском языке для озвучки и вывода в UI."""
    ui_status = result.get("ui_status", "")
    operation = result.get("operation", "")

    if ui_status in ("Не поняла", "Не поняла формат"):
        msg = "Извините, я не совсем поняла запрос. Повторите, пожалуйста."
        if result.get("hint"):
            msg += f" {result['hint']}."
        return msg

    if ui_status == "Уточнение" or operation == "clarify":
        return result.get("question") or "Уточните, пожалуйста, детали задачи."

    if operation == "delete":
        deleted = result.get("deleted")
        if deleted:
            return f"Удалила запись: «{deleted['action']}»."
        return f"Не нашла задачу по запросу «{result.get('search_query', '')}» для удаления."

    if operation == "complete":
        completed = result.get("completed")
        if completed:
            return f"Отметила выполненной задачу: «{completed['action']}»!"
        return f"Не нашла активную задачу «{result.get('search_query', '')}»."

    if ui_status == "Подтверждение":
        data = result.get("data") or {}
        kind = "Встреча" if data.get("intent") == "Meeting" else "Задача"
        parts = [f"{kind}: {data.get('action')}"]
        if data.get("date"):
            parts.append(f"на {data['date']}")
        if data.get("time"):
            parts.append(f"в {data['time']}")
        spoken = ", ".join(parts) + "."

        if data.get("date_warning"):
            spoken += f" Внимание: {data['date_warning']}."
        if data.get("date_in_past") == 1:
            spoken += " Эта дата уже в прошлом."
        if data.get("conflicts"):
            conflict_names = ", ".join(c["action"] for c in data["conflicts"])
            spoken += f" Конфликт времени с: {conflict_names}."

        spoken += " Всё верно?"
        return spoken

    if ui_status == "Зафиксировано":
        saved = result.get("saved") or {}
        kind = "Встреча" if saved.get("intent") == "Meeting" else "Задача"
        cal_note = " и добавлена в Календарь" if saved.get("parsed_date") else ""
        return f"Зафиксировано! {kind} «{saved.get('action', '')}» сохранена{cal_note}."

    if ui_status == "Готова" and operation == "cancel":
        return "Запись отменена. Готова к новому запросу."

    if operation == "list_period":
        items = result.get("items") or []
        period = result.get("period") or {}
        start_s = period.get("start", "")
        end_s = period.get("end", "")
        period_label = start_s if start_s == end_s else f"с {start_s} по {end_s}"
        if not items:
            return f"На период {period_label} запланированных дел нет."
        lines = [f"Планы ({period_label}) — всего {len(items)}:"]
        for idx, it in enumerate(items[:5], 1):
            t_str = f" в {it['parsed_time']}" if it.get("parsed_time") else ""
            d_str = f" ({it['parsed_date']})" if start_s != end_s and it.get("parsed_date") else ""
            lines.append(f"{idx}) {it['action']}{d_str}{t_str}")
        return " ".join(lines)

    if operation == "search":
        items = result.get("items") or []
        if not items:
            return "По вашему запросу ничего не найдено."
        top = items[0]
        d_str = f" на {top['parsed_date']}" if top.get("parsed_date") else ""
        t_str = f" в {top['parsed_time']}" if top.get("parsed_time") else ""
        status_str = " (Выполнено)" if top.get("status") == "Done" else ""
        return f"Нашла: «{top['action']}»{d_str}{t_str}{status_str}."

    return "Запрос обработан."


def run_agent_turn(
    user_query: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: str = "default",
    audio_duration_sec: float = 2.0
) -> Dict[str, Any]:
    agent = get_shared_agent()
    clean_lower = user_query.strip().lower().strip(".,!?")

    # 1. Если в буфере ждет задача на подтверждение
    if session_id in agent.pending_buffer:
        if clean_lower in CONFIRM_WORDS:
            res = agent.confirm_pending(session_id)
            res["spoken_response"] = format_spoken_response(res)
            return res
        if clean_lower in CANCEL_WORDS:
            res = agent.cancel_pending(session_id)
            res["spoken_response"] = format_spoken_response(res)
            return res

    res = agent.process_user_input(
        raw_text=user_query,
        session_id=session_id,
        audio_duration_sec=audio_duration_sec,
        auto_confirm=False
    )
    res["spoken_response"] = format_spoken_response(res)
    return res


def run_agent_loop(user_query: str, history: Optional[List[Dict[str, str]]] = None) -> str:
    turn_result = run_agent_turn(user_query=user_query, history=history)
    return turn_result["spoken_response"]
