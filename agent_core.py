import os
import re
import json
import time
import uuid
import urllib3
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dotenv import load_dotenv

from database import DatabaseManager, get_intent_label_ru, VALID_INTENTS
from tools_schema import build_system_prompt

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv(override=True)


def format_date_ru(date_str: Optional[str]) -> str:
    """Форматирует YYYY-MM-DD в ДД.ММ.ГГГГ для единого вывода на экран."""
    if not date_str:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return date_str


class RussianDateTimeExtractor:
    """
    Точное извлечение дат и времени из русской речи:
    - Корректная обработка «12 часов ночи» -> 00:00 и «12 часов дня» -> 12:00.
    - Автоматический перенос дат прошедших месяцев (январь, февраль и т.д.) на следующий год (2027).
    - Детектирование несуществующих календарных дат («31 февраля», «30 февраля», «31 апреля» и т.д.).
    """

    WORD_HOURS = {
        "двадцать четыре": 0, "двадцать три": 23, "двадцать два": 22, "двадцать один": 21,
        "двадцать": 20, "девятнадцать": 19, "восемнадцать": 18, "семнадцать": 17,
        "шестнадцать": 16, "пятнадцать": 15, "четырнадцать": 14, "тринадцать": 13,
        "двенадцать": 12, "двенадцати": 12, "двенадцатого": 12,
        "одиннадцать": 11, "одиннадцати": 11, "одиннадцатого": 11,
        "десять": 10, "десяти": 10, "десятого": 10,
        "девять": 9, "девяти": 9, "девятого": 9,
        "восемь": 8, "восьми": 8, "восьмого": 8,
        "семь": 7, "семи": 7, "седьмого": 7,
        "шесть": 6, "шести": 6, "шестого": 6,
        "пять": 5, "пяти": 5, "пятого": 5,
        "четыре": 4, "четырех": 4, "четырёх": 4, "четвертого": 4, "четвёртого": 4,
        "три": 3, "трех": 3, "трёх": 3, "третьего": 3,
        "два": 2, "двух": 2, "второго": 2,
        "час": 1, "один": 1, "одного": 1, "первого": 1,
        "ноль": 0
    }

    # Числительные дней месяца словами (от 31 до 1 для замены перед парсингом дат)
    WORD_DAYS = [
        (r"тридцать\s+вторых|тридцать\s+второго|тридцать\s+второе", 32),
        (r"тридцать\s+первого|тридцать\s+первое|тридцать\s+один", 31),
        (r"тридцатого|тридцатое|тридцать", 30),
        (r"двадцать\s+девятого|двадцать\s+девятое|двадцать\s+девять", 29),
        (r"двадцать\s+восьмого|двадцать\s+восьмое|двадцать\s+восемь", 28),
        (r"двадцать\s+седьмого|двадцать\s+седьмое|двадцать\s+семь", 27),
        (r"двадцать\s+шестого|двадцать\s+шестое|двадцать\s+шесть", 26),
        (r"двадцать\s+пятого|двадцать\s+пятое|двадцать\s+пять", 25),
        (r"двадцать\s+четв[её]ртого|двадцать\s+четв[её]ртое|двадцать\s+четыре", 24),
        (r"двадцать\s+третьего|двадцать\s+третье|двадцать\s+три", 23),
        (r"двадцать\s+второго|двадцать\s+второе|двадцать\s+два", 22),
        (r"двадцать\s+первого|двадцать\s+первое|двадцать\s+один", 21),
        (r"двадцатого|двадцатое|двадцать", 20),
        (r"девятнадцатого|девятнадцатое|девятнадцать", 19),
        (r"восемнадцатого|восемнадцатое|восемнадцать", 18),
        (r"семнадцатого|семнадцатое|семнадцать", 17),
        (r"шестнадцатого|шестнадцатое|шестнадцать", 16),
        (r"пятнадцатого|пятнадцатое|пятнадцать", 15),
        (r"четырнадцатого|четырнадцатое|четырнадцать", 14),
        (r"тринадцатого|тринадцатое|тринадцать", 13),
        (r"двенадцатого|двенадцатое", 12),
        (r"одиннадцатого|одиннадцатое", 11),
        (r"десятого|десятое", 10),
        (r"девятого|девятое", 9),
        (r"восьмого|восьмое", 8),
        (r"седьмого|седьмое", 7),
        (r"шестого|шестое", 6),
        (r"пятого|пятое", 5),
        (r"четв[её]ртого|четв[её]ртое", 4),
        (r"третьего|третье", 3),
        (r"второго|второе", 2),
        (r"первого|первое", 1),
    ]

    WEEKDAYS_MAP = {
        "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
        "четверг": 3, "пятницу": 4, "пятница": 4,
        "субботу": 5, "суббота": 5, "воскресенье": 6
    }

    MONTHS_MAP = {
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
        "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12
    }

    MONTH_REGEX_PART = (
        r"(январ[яеюь]?|феврал[яеюь]?|март[аеу]?|апрел[яеюь]?|ма[яеюй]|июн[яеюь]?|"
        r"июл[яеюь]?|август[аеу]?|сентябр[яеюь]?|октябр[яеюь]?|ноябр[яеюь]?|декабр[яеюь]?)"
    )

    @classmethod
    def _normalize_word_days_before_months(cls, text: str) -> str:
        """Превращает «тридцать первого февраля» -> «31 февраля», «пятнадцатого марта» -> «15 марта»."""
        res = text
        for word_pat, day_num in cls.WORD_DAYS:
            pattern = rf"\b(?:{word_pat})\s+{cls.MONTH_REGEX_PART}\b"
            res = re.sub(pattern, rf"{day_num} \1", res, flags=re.IGNORECASE)
        return res

    @staticmethod
    def _adjust_hour_by_period(h: int, period_context: str) -> int:
        p = period_context.lower()
        if "ноч" in p:
            if h == 12:
                return 0
            return h
        if "вечер" in p or "дня" in p or "день" in p:
            if 1 <= h <= 11:
                return h + 12
            if h == 12:
                return 12
        if "утр" in p and h == 12:
            return 0
        return h

    @staticmethod
    def _resolve_year_for_month_day(month: int, day: int, explicit_year: Optional[int], now: datetime) -> datetime:
        """
        Вычисляет дату. Если год не указан явно, а дата в текущем году уже прошла (например, февраль при текущем октябре),
        автоматически ставит следующий год (now.year + 1).
        Выбрасывает ValueError, если дата не существует в календаре (например, 31 февраля).
        """
        if explicit_year is not None:
            return datetime(explicit_year, month, day)

        # Проверяем в текущем году; если дата уже прошла — переносим на следующий год
        try:
            candidate = datetime(now.year, month, day)
            if candidate.date() < now.date():
                return datetime(now.year + 1, month, day)
            return candidate
        except ValueError:
            # Например, 29 февраля: проверим, не является ли следующий год високосным, если этот месяц уже прошёл
            if (month, day) < (now.month, now.day):
                return datetime(now.year + 1, month, day)
            raise

    @classmethod
    def extract_date_and_time_full(
        cls, text: str, now: datetime
    ) -> Tuple[Optional[str], Optional[str], str, Optional[str]]:
        """
        Возвращает кортеж: (parsed_date, parsed_time, clean_text_without_datetime, invalid_date_error).
        Если пользователь назвал несуществующую дату («31 февраля»), invalid_date_error содержит эту фразу.
        """
        clean = cls._normalize_word_days_before_months(text)
        lower = clean.lower()
        parsed_time: Optional[str] = None
        parsed_date: Optional[str] = None
        invalid_date_str: Optional[str] = None

        # 0. Явный перехват «12 часов ночи» / «двенадцать ночи» / «полночь» и «12 часов дня» / «полдень»
        midnight_m = re.search(
            r"\b(?:в|на|к)?\s*(?:12|двенадцат[ьи])\s*(?:час(?:а|ов|у)?\s*)?ночи\b|\b(?:в|на)?\s*полночь\b",
            lower
        )
        noon_m = re.search(
            r"\b(?:в|на|к)?\s*(?:12|двенадцат[ьи])\s*(?:час(?:а|ов|у)?\s*)?дня\b|\b(?:в|на)?\s*полдень\b",
            lower
        )
        if midnight_m:
            parsed_time = "00:00"
            clean = clean[:midnight_m.start()] + " " + clean[midnight_m.end():]
            lower = clean.lower()
        elif noon_m:
            parsed_time = "12:00"
            clean = clean[:noon_m.start()] + " " + clean[noon_m.end():]
            lower = clean.lower()

        # 1. Время в формате HH:MM или HH.MM (но не дата вида 15.02.2027)
        if not parsed_time:
            tm = re.search(
                r"(?:(?:\bв|\bна|\bк)\s+)?\b([0-2]?\d)[:.]([0-5]\d)(?!\.\d{2,4})\b(?:\s*(утра|вечера|дня|ночи))?",
                lower
            )
            if tm:
                # Убеждаемся, что точка не является датой DD.MM без предлога времени
                is_date_dot = "." in tm.group(0) and not re.search(r"\b(?:в|к)\s+\d", tm.group(0))
                if not is_date_dot:
                    h, m = int(tm.group(1)), int(tm.group(2))
                    if 0 <= h <= 23:
                        h = cls._adjust_hour_by_period(h, tm.group(3) or lower)
                        parsed_time = f"{h:02d}:{m:02d}"
                        clean = clean[:tm.start()] + " " + clean[tm.end():]
                        lower = clean.lower()

        # 2. «в половине <часа>»
        if not parsed_time:
            half_m = re.search(r"\b(?:в\s+)?половине\s+([а-яё]+)(?:\s+(утра|дня|вечера|ночи))?", lower)
            if half_m and half_m.group(1) in cls.WORD_HOURS:
                target_h = cls.WORD_HOURS[half_m.group(1)] - 1
                period_ctx = half_m.group(2) or lower
                if target_h == 11 and "ноч" in period_ctx:
                    target_h = 23
                elif ("вечер" in period_ctx or "дня" in period_ctx or 1 <= target_h <= 6) and target_h < 12 and "утр" not in period_ctx and "ноч" not in period_ctx:
                    target_h += 12
                parsed_time = f"{target_h % 24:02d}:30"
                clean = clean[:half_m.start()] + " " + clean[half_m.end():]
                lower = clean.lower()

        # 3. Время цифрами: «в 15 часов», «в 3 часа дня», «в 12 ночи», «в 7 вечера»
        if not parsed_time:
            hm = re.search(
                r"\b(?:(?:в|на|к)\s+([0-2]?\d)\s*(?:час(?:а|ов|у)?)?(?:\s*(утра|вечера|дня|ночи))?|"
                r"([0-2]?\d)\s*(?:час(?:а|ов|у)?\s+)?(утра|вечера|дня|ночи))\b",
                lower
            )
            if hm:
                # Проверяем, что после числа не идёт название месяца (например «на 15 февраля»)
                after_slice = lower[hm.end():].lstrip()
                if not re.match(cls.MONTH_REGEX_PART, after_slice):
                    h_str = hm.group(1) if hm.group(1) is not None else hm.group(3)
                    period_word = hm.group(2) or hm.group(4) or ""
                    h = int(h_str)
                    if 0 <= h <= 24:
                        if h == 24:
                            h = 0
                        else:
                            h = cls._adjust_hour_by_period(h, period_word or lower)
                        parsed_time = f"{h:02d}:00"
                        clean = clean[:hm.start()] + " " + clean[hm.end():]
                        lower = clean.lower()

        # 4. Время словами: «в три часа дня», «в час ночи», «в двенадцать ночи»
        if not parsed_time:
            for word, h_val in sorted(cls.WORD_HOURS.items(), key=lambda x: -len(x[0])):
                pat = rf"\b(?:(?:в|на|к)\s+{word}(?:\s+час(?:а|ов|у)?)?(?:\s+(утра|дня|вечера|ночи))?|{word}\s+(?:час(?:а|ов|у)?\s+)?(утра|дня|вечера|ночи))\b"
                wm = re.search(pat, lower)
                if wm:
                    after_slice = lower[wm.end():].lstrip()
                    if re.match(cls.MONTH_REGEX_PART, after_slice):
                        continue
                    period = wm.group(1) or wm.group(2) or ""
                    h = cls._adjust_hour_by_period(h_val, period or lower)
                    if 0 <= h <= 23:
                        parsed_time = f"{h:02d}:00"
                        clean = clean[:wm.start()] + " " + clean[wm.end():]
                        lower = clean.lower()
                        break

        # 5. Даты с названием месяца («15 февраля», «31 февраля», «10 марта 2027 года»)
        month_m = re.search(
            rf"(?:\b(?:на|в)\s+)?\b(\d{{1,2}})\s+{cls.MONTH_REGEX_PART}(?:\s+(\d{{4}})\s*(?:год[ау]?|г\.?)?)?\b",
            clean.lower()
        )
        if month_m:
            d = int(month_m.group(1))
            m_word = month_m.group(2)
            explicit_y = int(month_m.group(3)) if month_m.group(3) else None
            m_prefix = m_word[:5]
            m_num = next((v for k, v in cls.MONTHS_MAP.items() if m_prefix.startswith(k)), now.month)
            raw_matched_date = f"{d} {m_word}"
            clean = clean[:month_m.start()] + " " + clean[month_m.end():]
            lower = clean.lower()
            try:
                dt = cls._resolve_year_for_month_day(m_num, d, explicit_y, now)
                parsed_date = dt.strftime("%Y-%m-%d")
            except ValueError:
                invalid_date_str = raw_matched_date

        # 6. Даты формата DD.MM(.YYYY)
        if not parsed_date and not invalid_date_str:
            dm_match = re.search(r"(?:\bна\s+)?\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", clean.lower())
            if dm_match:
                d, m = int(dm_match.group(1)), int(dm_match.group(2))
                explicit_y = int(dm_match.group(3)) if dm_match.group(3) else None
                raw_matched_date = dm_match.group(0).strip()
                clean = clean[:dm_match.start()] + " " + clean[dm_match.end():]
                lower = clean.lower()
                try:
                    dt = cls._resolve_year_for_month_day(m, d, explicit_y, now)
                    parsed_date = dt.strftime("%Y-%m-%d")
                except ValueError:
                    invalid_date_str = raw_matched_date

        # 7. Относительные даты: послезавтра, завтра, сегодня, вчера, через неделю
        if not parsed_date and not invalid_date_str:
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

        # 8. Дни недели: «в пятницу», «на субботу»
        if not parsed_date and not invalid_date_str:
            for day_word, target_wd in cls.WEEKDAYS_MAP.items():
                wd_m = re.search(rf"\b(?:в|во|на)\s+(?:следующ[уюийе]+\s+)?{day_word}\b", clean.lower())
                if wd_m:
                    days_ahead = (target_wd - now.weekday()) % 7 or 7
                    parsed_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                    clean = clean[:wd_m.start()] + " " + clean[wd_m.end():]
                    break

        clean = re.sub(r"\b\d{4}\s*(?:год[ау]?|г\.?)\b", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" ,.-?!")
        return parsed_date, parsed_time, clean, invalid_date_str

    @classmethod
    def extract_date_and_time(cls, text: str, now: datetime) -> Tuple[Optional[str], Optional[str], str]:
        d, t, clean, _ = cls.extract_date_and_time_full(text, now)
        return d, t, clean


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

        dt_date, dt_time, _, invalid_dt = RussianDateTimeExtractor.extract_date_and_time_full(clean, now)

        llm_date = None if invalid_dt else (llm_parsed or {}).get("date")
        llm_time = (llm_parsed or {}).get("time")
        final_date = dt_date or llm_date
        final_time = dt_time or llm_time
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
    """Точный классификатор типов (Task, Reminder, Meeting) и локальный парсер."""

    MEETING_KEYWORDS = (
        "встреч", "встретиться", "пересечься", "созвон", "созвониться", "звонок с",
        "конференц", "зум", "zoom", "мит", "meet", "скайп", "тимс",
        "обед с", "ужин с", "завтрак с", "кофе с", "свидан",
        "приём", "прием", "к врачу", "у врача", "стоматолог", "терапевт",
        "хирург", "окулист", "невролог", "психолог", "парикмахер", "барбер",
        "маникюр", "нотариус", "юрист", "консультац", "собеседован",
        "планёрк", "планерк", "переговор", "лекци", "семинар", "репетитор", "тренировка с"
    )

    REMINDER_KEYWORDS = (
        "напомни", "напоминан", "напоминалк", "не забыть", "не забудь", "вспомнить",
        "выпить таблет", "принять таблет", "таблетк", "лекарств", "витамин",
        "поздравить", "с днем рождения", "с днём рождения", "с др",
        "оплатить", "заплатить", "квартплат", "жкх", "подписк", "налог", "кредит",
        "продлить", "выключить", "полить", "покормить", "забрать посылк", "забрать заказ"
    )

    TASK_PREP_BEFORE_MEETING = (
        "подготовить", "написать", "сделать", "составить", "отправить", "сдать", "проверить"
    )

    PARASITE_WORDS = (
        r"(?:^|\s)(ну|эээ|типа|короче|значит так|значит|как его|надо|там|это|вот|"
        r"пожалуйста|ворон[а]?|поставь|поставить|запиши|записать|создай|создать|добавь|добавить|"
        r"назначь|назначить|сделай\s+напоминание|напоминание|напоминания|напоминалку|"
        r"напомни\s+мне|напомни|задачу|задача|событие)(?=\s|$)"
    )

    @classmethod
    def detect_intent(cls, text: str, llm_intent: Optional[str] = None) -> str:
        lower = text.lower()

        # 1. Явные голосовые команды выбора типа («поставь задачу», «поставь напоминание», «назначь встречу»)
        if re.search(r"\b(?:поставь|создай|добавь|запиши|новая)\s+задач[уаи]\b", lower):
            return "Task"
        if re.search(r"\b(?:назначь|создай|добавь|запиши|поставь)\s+встреч[уаи]\b", lower):
            return "Meeting"
        if re.search(r"\b(?:поставь|создай|добавь|сделай|запиши)\s+напоминан[иея]\b|\b(?:напомни|не\s+забыть|не\s+забудь)\b", lower):
            # Если внутри фразы «напомни о встрече с...» явно идёт встреча, проверим контекст
            if any(k in lower for k in ("встреч", "созвон", "обед с", "собеседован")):
                return "Meeting"
            return "Reminder"

        # 2. Проверка на Встречу (Meeting)
        if "совещан" in lower and not any(p in lower for p in cls.TASK_PREP_BEFORE_MEETING):
            return "Meeting"
        if any(k in lower for k in cls.MEETING_KEYWORDS) and "повестк" not in lower:
            return "Meeting"

        # 3. Проверка на Напоминание (Reminder)
        if any(k in lower for k in cls.REMINDER_KEYWORDS):
            return "Reminder"

        # 4. Если LLM вернула валидный тип — используем его, иначе Task
        if llm_intent in VALID_INTENTS:
            return llm_intent
        return "Task"

    @classmethod
    def clean_action_text(cls, text: str, now: datetime) -> Optional[str]:
        _, _, clean, _ = RussianDateTimeExtractor.extract_date_and_time_full(text, now)
        # Если сказали «назначь встречу с Иваном», превращаем «встречу с» -> «Встреча с»
        clean = re.sub(
            r"\b(?:назначь|запиши|поставь|создай|добавь)\s+встречу\s+(с|со|у|в|на)\b",
            r"Встреча \1",
            clean,
            flags=re.IGNORECASE
        )
        clean = re.sub(r"\b(?<!на\s)(?<!про\s)встречу\s*$", " ", clean, flags=re.IGNORECASE)
        for _ in range(3):
            clean = re.sub(cls.PARASITE_WORDS, " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^(?:на|в|к|про|о|об|мне)\s+", "", clean.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\b(?:на|в|к)\s*$", "", clean.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" ,.-?!")
        if not clean:
            return None
        return clean[0].upper() + clean[1:]

    @classmethod
    def parse_standalone_command(cls, text: str, now: datetime) -> Optional[Dict[str, Any]]:
        clean = text.strip()
        lower_text = clean.lower()

        if VoiceUpdateExtractor.is_update_command(clean):
            return VoiceUpdateExtractor.extract(clean, now)

        del_match = re.search(r"^(?:удали|удалить|убери|убрать|отмени|отменить|сотри)\s+(.+)", lower_text)
        if del_match:
            q = re.sub(r"\b(задачу|встречу|напоминание|напоминания|дело|про|по)\b", "", del_match.group(1)).strip(" ,.?!")
            return {
                "operation": "delete",
                "intent": None,
                "action": None,
                "date": None,
                "end_date": None,
                "time": None,
                "search_query": q or del_match.group(1)
            }

        done_match = re.search(
            r"(?:отметь|отметить|заверши|завершить|выполнил[а]?|сделал[а]?|закрой|закрыть)\s+(.+)",
            lower_text
        )
        if done_match or "выполненной" in lower_text or "выполнено" in lower_text:
            q = re.sub(
                r"\b(отметь|отметить|заверши|задачу|встречу|напоминание|дело|как|выполненной|выполненную|выполнено|сделанной|про|по)\b",
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

        search_match = re.search(r"(?:найди|найти|поищи|искать|когда\s+у\s+меня\s+был[аои]?)\s+(.+)", lower_text)
        if search_match or "найди ее" in lower_text or "найди её" in lower_text:
            q = re.sub(r"\b(задачу|встречу|напоминание|про|по|я когда-то ставил|найди ее|найди её)\b", "", lower_text).strip(" ,.?!")
            return {
                "operation": "search",
                "intent": None,
                "action": None,
                "date": None,
                "end_date": None,
                "time": None,
                "search_query": q or clean
            }

        if re.search(
            r"\b(что у меня|какие дела|какие задачи|какие встречи|какие напоминания|"
            r"какие планы|есть ли встречи|что запланировано|покажи задачи|покажи встречи|покажи планы)\b",
            lower_text
        ):
            start_date = now.strftime("%Y-%m-%d")
            end_date = start_date
            if "послезавтра" in lower_text:
                start_date = (now + timedelta(days=2)).strftime("%Y-%m-%d")
                end_date = start_date
            elif "завтра" in lower_text:
                start_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                end_date = start_date
            elif "недел" in lower_text:
                days_until_sunday = 6 - now.weekday()
                end_date = (now + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")

            intent_filter = None
            if "встреч" in lower_text:
                intent_filter = "Meeting"
            elif "напоминан" in lower_text:
                intent_filter = "Reminder"
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

        return None

    @classmethod
    def parse(cls, text: str, now: datetime) -> Optional[Dict[str, Any]]:
        clean = text.strip()
        if len(clean) < 2:
            return None

        standalone = cls.parse_standalone_command(clean, now)
        if standalone:
            return standalone

        intent = cls.detect_intent(clean)
        parsed_date, parsed_time, _, invalid_dt = RussianDateTimeExtractor.extract_date_and_time_full(clean, now)
        action = cls.clean_action_text(clean, now)

        if not action and not parsed_date and not parsed_time and not invalid_dt:
            return {"operation": "none", "intent": None, "action": None, "date": None, "time": None}

        is_complete = bool(action and parsed_date and parsed_time and not invalid_dt)
        return {
            "operation": "create" if is_complete else "clarify",
            "intent": intent,
            "action": action,
            "date": None if invalid_dt else parsed_date,
            "end_date": None,
            "time": parsed_time,
            "search_query": None,
            "question": None
        }


class GigaChatClient:
    """Прямой легковесный клиент GigaChat API поверх httpx."""

    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self, credentials: str, scope: str = "GIGACHAT_API_PERS"):
        self.credentials = re.sub(r"^(Basic|Bearer)\s+", "", credentials.strip(), flags=re.IGNORECASE)
        self.scope = scope
        self.http = httpx.Client(verify=False, timeout=12.0)
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def _ensure_token(self) -> str:
        now_ts = time.time()
        if self._access_token and now_ts < self._expires_at - 60:
            return self._access_token

        resp = self.http.post(
            self.OAUTH_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {self.credentials}",
            },
            data={"scope": self.scope}
        )
        if resp.status_code != 200:
            raise RuntimeError(f"GigaChat OAuth error {resp.status_code}")

        token_data = resp.json()
        self._access_token = token_data["access_token"]
        exp_ms = token_data.get("expires_at", (now_ts + 1800) * 1000)
        self._expires_at = float(exp_ms) / 1000.0
        return self._access_token

    def complete_json(self, system_prompt: str, user_text: str) -> Optional[Dict[str, Any]]:
        token = self._ensure_token()
        payload = {
            "model": "GigaChat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Текст: {user_text}"}
            ],
            "temperature": 0.0,
            "max_tokens": 250
        }

        resp = self.http.post(
            self.CHAT_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload
        )
        if resp.status_code == 401:
            self._access_token = None
            token = self._ensure_token()
            resp = self.http.post(
                self.CHAT_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload
            )

        if resp.status_code != 200:
            return None

        content = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content") or ""
        )
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx == -1 or end_idx <= start_idx:
            return None
        return json.loads(content[start_idx : end_idx + 1])


class VoronaAgentCore:
    """Ядро голосового ассистента «Ворона»."""

    def __init__(self, db: DatabaseManager, **_kwargs):
        self.db = db
        gigachat_creds = (os.getenv("GIGACHAT_CREDENTIALS") or os.getenv("GIGACHAT_API_KEY") or "").strip()
        gigachat_scope = (os.getenv("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS").strip()
        self.gigachat = GigaChatClient(gigachat_creds, gigachat_scope) if gigachat_creds else None

        if self.gigachat:
            print("🔑 [LLM] Подключен провайдер: GigaChat")
        else:
            print("⚠️ [LLM] Ключ GigaChat не задан, работает локальный RegEx-парсер.")

        self.pending_buffer: Dict[str, Dict[str, Any]] = {}
        self.rollback_buffer: Dict[str, Dict[str, Any]] = {}
        self.fail_streak: Dict[str, int] = {}

    @staticmethod
    def _make_session_key(user_id: int, session_id: str) -> str:
        return f"user_{user_id}_{session_id}"

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

    @classmethod
    def _ensure_future_year(cls, date_str: Optional[str], raw_text: str, now: datetime) -> Optional[str]:
        """
        Если LLM вернула дату в текущем году (например, 2026-02-15), которая уже в прошлом,
        а пользователь НЕ называл явно 2026 год или слово «вчера», автоматически переносит год на 2027.
        """
        valid = cls._validate_calendar_date(date_str)
        if not valid:
            return None
        dt = datetime.strptime(valid, "%Y-%m-%d")
        lower = raw_text.lower()
        explicit_past = str(now.year) in lower or "вчера" in lower or "прошл" in lower
        if dt.date() < now.date() and not explicit_past:
            try:
                return dt.replace(year=now.year + 1).strftime("%Y-%m-%d")
            except ValueError:
                return None
        return valid

    @staticmethod
    def _validate_time(time_str: Optional[str]) -> Optional[str]:
        if not time_str or not isinstance(time_str, str):
            return None
        if not re.match(r"^[0-2]\d:[0-5]\d$", time_str):
            return None
        h, m = map(int, time_str.split(":"))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
        return None

    @staticmethod
    def _sanitize_action(action_candidate: Optional[str], now: datetime) -> Optional[str]:
        if not action_candidate or not isinstance(action_candidate, str):
            return None
        clean = action_candidate.strip()
        lower = clean.lower()
        if "?" in clean or any(
            lower.startswith(q) for q in (
                "уточните", "на какое", "на какую", "какое событие", "когда", "во сколько", "такой даты"
            )
        ):
            return None
        return RegexFallbackParser.clean_action_text(clean, now)

    @staticmethod
    def _build_missing_question(
        action: Optional[str],
        parsed_date: Optional[str],
        parsed_time: Optional[str],
        invalid_date_str: Optional[str] = None,
        llm_question: Optional[str] = None
    ) -> str:
        known_parts = []
        if action:
            known_parts.append(f"«{action}»")
        if parsed_date:
            known_parts.append(format_date_ru(parsed_date))
        if parsed_time:
            known_parts.append(parsed_time)

        prefix = f"{', '.join(known_parts)}. " if known_parts else ""

        if invalid_date_str:
            missing_extra = []
            if not action:
                missing_extra.append("название события")
            if not parsed_time:
                missing_extra.append("время")
            extra_str = f" и {' и '.join(missing_extra)}" if missing_extra else ""
            return f"{prefix}Даты «{invalid_date_str}» не существует в календаре. Уточните корректную дату{extra_str}."

        missing = []
        if not action:
            missing.append("название события")
        if not parsed_date:
            missing.append("дату")
        if not parsed_time:
            missing.append("время")

        if llm_question and "?" in llm_question and len(missing) == 1:
            return f"{prefix}{llm_question}"

        if len(missing) == 1:
            return f"{prefix}Уточните {missing[0]}."
        elif len(missing) == 2:
            return f"{prefix}Уточните {missing[0]} и {missing[1]}."
        return "Уточните название события, дату и время."

    def _register_failure(self, session_key: str, error_code: str, ui_status: str = "Не поняла") -> Dict[str, Any]:
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
        if not self.gigachat:
            return None
        try:
            active_items = self.db.get_history(limit=20, status_filter="Active", sort_by="date", user_id=user_id)
            sys_prompt = build_system_prompt(now, active_items=active_items)
            return self.gigachat.complete_json(sys_prompt, raw_text)
        except Exception as exc:
            print(f"⚠️ [GigaChat] Ошибка ({type(exc).__name__}), использую RegEx.")
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

        # Если новая реплика — самостоятельная команда (удали, перенеси, найди, что у меня), сбрасываем черновик
        if RegexFallbackParser.parse_standalone_command(clean_input, now) is not None:
            self.pending_buffer.pop(session_key, None)

        # Извлекаем дату, время и проверяем на несуществующую дату («31 февраля») в текущей реплике
        dt_date_new, dt_time_new, clean_input_no_dt, invalid_date_new = (
            RussianDateTimeExtractor.extract_date_and_time_full(clean_input, now)
        )
        action_from_new = RegexFallbackParser.clean_action_text(clean_input, now)

        prev_staged = self.pending_buffer.get(session_key)
        if prev_staged:
            combined_input = f"{prev_staged.get('raw_text', '')}. {clean_input}".strip(" .")
        else:
            combined_input = clean_input

        parse_method = "llm"
        parsed_data = self._call_llm_json(combined_input, now, user_id=user_id)

        if not isinstance(parsed_data, dict) or "operation" not in parsed_data:
            parse_method = "regex"
            parsed_data = RegexFallbackParser.parse(combined_input, now)
            if not parsed_data:
                return self._register_failure(session_key, "E07", "Не поняла формат")

        operation = parsed_data.get("operation")

        if not prev_staged:
            if VoiceUpdateExtractor.is_update_command(clean_input) or operation == "update":
                if invalid_date_new:
                    return {
                        "ui_status": "Уточнение",
                        "operation": "clarify",
                        "requires_confirmation": False,
                        "question": f"Даты «{invalid_date_new}» не существует в календаре. На какую дату перенести запись?"
                    }
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
                new_date = self._ensure_future_year(parsed_data.get("date"), clean_input, now)
                new_time = dt_time_new or self._validate_time(parsed_data.get("time"))
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

                if new_action and (
                    new_action.strip().lower() == target_item["action"].strip().lower()
                    or VoiceUpdateExtractor.is_update_command(new_action)
                    or new_action.strip().lower() in query.strip().lower()
                ):
                    new_action = None

                self.rollback_buffer[session_key] = dict(target_item)
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

        llm_action = self._sanitize_action(parsed_data.get("action"), now)
        llm_time = self._validate_time(parsed_data.get("time"))
        llm_intent = parsed_data.get("intent") if parsed_data.get("intent") in VALID_INTENTS else None

        # Если обнаружена несуществующая дата (например «31 февраля»), блокируем любую придуманную LLM дату!
        if invalid_date_new:
            llm_date = None
            dt_date_new = None
        else:
            llm_date = self._ensure_future_year(parsed_data.get("date"), combined_input, now)

        dt_date_combined, _, _, _ = RussianDateTimeExtractor.extract_date_and_time_full(combined_input, now)
        has_any_date_word = bool(
            dt_date_combined
            or any(w in combined_input.lower() for w in ("сегодня", "завтра", "послезавтра", "недел", "числ", "месяц"))
        )
        if not has_any_date_word and not (prev_staged and prev_staged.get("parsed_date")):
            llm_date = None

        # Приоритет локального парсера дат и времени (особенно для «12 часов ночи» -> 00:00 и переноса на 2027 год)
        if prev_staged:
            validated_date = None if invalid_date_new else (dt_date_new or llm_date or prev_staged.get("parsed_date"))
            validated_time = dt_time_new or llm_time or prev_staged.get("parsed_time")
            action = prev_staged.get("action") or action_from_new or llm_action
        else:
            validated_date = None if invalid_date_new else (dt_date_new or llm_date)
            validated_time = dt_time_new or llm_time
            action = action_from_new or llm_action

        # Определяем тип (Task / Reminder / Meeting) по полному контексту реплик
        prev_intent = prev_staged.get("intent") if prev_staged else None
        intent = RegexFallbackParser.detect_intent(
            combined_input,
            llm_intent=llm_intent or (prev_intent if prev_intent in ("Meeting", "Reminder") else None)
        )

        if not action and not validated_date and not validated_time and not invalid_date_new:
            return self._register_failure(session_key, "E03_E04", "Не поняла")

        self.fail_streak[session_key] = 0
        date_in_past = 1 if (validated_date and validated_date < today_str) else 0

        # Если в реплике была некорректная дата («31 февраля»), не сохраняем её в черновик raw_text,
        # чтобы на следующем шаге уточнения она не вызывала повторную ошибку
        safe_raw_for_stage = combined_input
        if invalid_date_new:
            safe_raw_for_stage = action or clean_input_no_dt

        staged_record = {
            "user_id": user_id,
            "intent": intent,
            "raw_text": safe_raw_for_stage,
            "action": action,
            "parsed_date": validated_date,
            "parsed_time": validated_time,
            "date_in_past": date_in_past,
            "parse_method": parse_method,
            "now_override": now
        }
        self.pending_buffer[session_key] = staged_record

        is_complete = bool(action and validated_date and validated_time and not invalid_date_new)

        if not is_complete:
            question = self._build_missing_question(
                action=action,
                parsed_date=validated_date,
                parsed_time=validated_time,
                invalid_date_str=invalid_date_new,
                llm_question=parsed_data.get("question")
            )
            return {
                "ui_status": "Уточнение",
                "operation": "clarify",
                "requires_confirmation": True,
                "question": question,
                "data": {
                    "intent": intent,
                    "raw_text": safe_raw_for_stage,
                    "action": action,
                    "date": validated_date,
                    "time": validated_time
                }
            }

        conflicts = (
            self.db.check_meeting_conflict(validated_date, validated_time, user_id=user_id)
            if (intent == "Meeting" and validated_date and validated_time)
            else []
        )

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
                "parse_method": parse_method,
                "conflicts": conflicts
            }
        }

    def confirm_pending(self, session_id: str = "default", user_id: int = 1) -> Dict[str, Any]:
        session_key = self._make_session_key(user_id, session_id)
        self.rollback_buffer.pop(session_key, None)
        staged = self.pending_buffer.get(session_key)
        if not staged:
            return {"ui_status": "Готова", "operation": "noop", "requires_confirmation": False, "saved": None}

        now = staged.get("now_override") or datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        final_action = (staged.get("action") or "").strip() or "Событие"
        final_date = staged.get("parsed_date") or (now + timedelta(days=1)).strftime("%Y-%m-%d")
        final_time = staged.get("parsed_time") or "11:00"
        final_intent = staged.get("intent") if staged.get("intent") in VALID_INTENTS else "Task"

        try:
            saved_item = self.db.save_confirmed_item(
                intent=final_intent,
                raw_text=staged.get("raw_text") or final_action,
                action=final_action,
                parsed_date=final_date,
                parsed_time=final_time,
                date_in_past=1 if final_date < today_str else 0,
                parse_method=staged.get("parse_method", "llm"),
                now_override=now,
                user_id=user_id
            )
            self.pending_buffer.pop(session_key, None)
            return {
                "ui_status": "Зафиксировано",
                "operation": "create",
                "requires_confirmation": False,
                "saved": saved_item
            }
        except Exception:
            return {
                "ui_status": "Ошибка записи",
                "error_code": "E22",
                "can_retry": True,
                "saved": None
            }

    def cancel_pending(self, session_id: str = "default", user_id: int = 1) -> Dict[str, Any]:
        session_key = self._make_session_key(user_id, session_id)
        self.pending_buffer.pop(session_key, None)

        prev_state = self.rollback_buffer.pop(session_key, None)
        if prev_state:
            self.db.update_item(
                task_id=prev_state["id"],
                action=prev_state["action"],
                parsed_date=prev_state["parsed_date"],
                parsed_time=prev_state["parsed_time"],
                intent=prev_state["intent"],
                status=prev_state["status"],
                user_id=user_id
            )

        return {
            "ui_status": "Готова",
            "operation": "cancel",
            "requires_confirmation": False
        }


_default_db: Optional[DatabaseManager] = None
_default_agent: Optional[VoronaAgentCore] = None

CONFIRM_WORDS = {"да", "верно", "подтверждаю", "сохрани", "сохранить", "ок", "окей", "ага", "правильно", "точно"}
CANCEL_WORDS = {"нет", "неверно", "отмена", "отменить", "сброс", "не надо"}


def get_shared_agent() -> VoronaAgentCore:
    global _default_db, _default_agent
    if _default_agent is None:
        _default_db = DatabaseManager(db_path=":memory:")
        _default_agent = VoronaAgentCore(db=_default_db)
    return _default_agent


def format_spoken_response(result: Dict[str, Any]) -> str:
    ui_status = result.get("ui_status", "")
    operation = result.get("operation", "")

    if ui_status in ("Не поняла", "Не поняла формат"):
        msg = "Извините, я не совсем поняла запрос. Повторите, пожалуйста."
        if result.get("hint"):
            msg += f" {result['hint']}."
        return msg

    if ui_status == "Уточнение" or operation == "clarify":
        return result.get("question") or "Уточните, пожалуйста, детали события."

    if operation == "delete":
        deleted = result.get("deleted")
        if deleted:
            kind = get_intent_label_ru(deleted.get("intent"))
            return f"Удалила из списка и календаря ({kind.lower()}): «{deleted['action']}»."
        return f"Не нашла запись по запросу «{result.get('search_query', '')}» для удаления."

    if operation == "complete":
        completed = result.get("completed")
        if completed:
            kind = get_intent_label_ru(completed.get("intent"))
            return f"Отметила выполненной ({kind.lower()}): «{completed['action']}»!"
        return f"Не нашла активную запись «{result.get('search_query', '')}»."

    if operation == "update":
        updated = result.get("updated")
        old_item = result.get("old_item") or {}
        if updated:
            kind = get_intent_label_ru(updated.get("intent"))
            d_part = f" на {format_date_ru(updated['parsed_date'])}" if updated.get("parsed_date") else ""
            t_part = f" в {updated['parsed_time']}" if updated.get("parsed_time") else ""
            if old_item.get("action") and old_item.get("action") != updated.get("action"):
                return f"Изменила «{old_item['action']}» на «{updated['action']}»{d_part}{t_part}."
            return f"Перенесла ({kind.lower()}): «{updated['action']}»{d_part}{t_part}."
        return f"Не нашла запись «{result.get('search_query', '')}» для изменения."

    if ui_status == "Подтверждение":
        data = result.get("data") or {}
        kind = get_intent_label_ru(data.get("intent"))
        parts = [f"{kind}: «{data.get('action')}»"]
        if data.get("date"):
            parts.append(f"на {format_date_ru(data['date'])}")
        if data.get("time"):
            parts.append(f"в {data['time']}")
        spoken = ", ".join(parts) + "."

        if data.get("date_in_past") == 1:
            spoken += " Эта дата уже в прошлом."
        if data.get("conflicts"):
            conflict_names = ", ".join(c["action"] for c in data["conflicts"])
            spoken += f" Конфликт времени с: {conflict_names}."

        spoken += " Всё верно?"
        return spoken

    if ui_status == "Зафиксировано":
        saved = result.get("saved") or {}
        kind = get_intent_label_ru(saved.get("intent"))
        d_str = format_date_ru(saved.get("parsed_date"))
        t_str = saved.get("parsed_time") or ""
        when_note = f" на {d_str} в {t_str}" if (d_str and t_str) else (f" на {d_str}" if d_str else "")
        return f"Зафиксировано! {kind} «{saved.get('action', '')}»{when_note} сохранена."

    if ui_status == "Готова" and operation == "cancel":
        return "Запись отменена. Готова к новому запросу."

    if operation == "list_period":
        items = result.get("items") or []
        period = result.get("period") or {}
        start_s = format_date_ru(period.get("start"))
        end_s = format_date_ru(period.get("end"))
        period_label = start_s if start_s == end_s else f"с {start_s} по {end_s}"
        if not items:
            return f"На период {period_label} запланированных дел нет."
        lines = [f"Планы ({period_label}) — всего {len(items)}:"]
        for idx, it in enumerate(items[:5], 1):
            kind = get_intent_label_ru(it.get("intent"))
            t_str = f" в {it['parsed_time']}" if it.get("parsed_time") else ""
            d_str = f" ({format_date_ru(it['parsed_date'])})" if start_s != end_s and it.get("parsed_date") else ""
            lines.append(f"{idx}) [{kind}] {it['action']}{d_str}{t_str}")
        return " ".join(lines)

    if operation == "search":
        items = result.get("items") or []
        if not items:
            return "По вашему запросу ничего не найдено."
        top = items[0]
        kind = get_intent_label_ru(top.get("intent"))
        d_str = f" на {format_date_ru(top['parsed_date'])}" if top.get("parsed_date") else ""
        t_str = f" в {top['parsed_time']}" if top.get("parsed_time") else ""
        status_str = " (Выполнено)" if top.get("status") == "Done" else ""
        return f"Нашла ({kind.lower()}): «{top['action']}»{d_str}{t_str}{status_str}."

    return "Готова!"


def run_agent_turn(
    user_query: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: str = "default",
    audio_duration_sec: float = 2.0,
    user_id: int = 1
) -> Dict[str, Any]:
    agent = get_shared_agent()
    session_key = agent._make_session_key(user_id, session_id)
    clean_lower = user_query.strip().lower().strip(".,!?")

    if session_key in agent.pending_buffer:
        if clean_lower in CONFIRM_WORDS:
            res = agent.confirm_pending(session_id=session_id, user_id=user_id)
            res["spoken_response"] = format_spoken_response(res)
            return res
        if clean_lower in CANCEL_WORDS:
            res = agent.cancel_pending(session_id=session_id, user_id=user_id)
            res["spoken_response"] = format_spoken_response(res)
            return res

    res = agent.process_user_input(
        raw_text=user_query,
        session_id=session_id,
        audio_duration_sec=audio_duration_sec,
        auto_confirm=False,
        user_id=user_id
    )
    res["spoken_response"] = format_spoken_response(res)
    return res

