from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

DAYS_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье"
]


def build_calendar_cheat_sheet(now: datetime) -> str:
    lines = []
    for offset in range(1, 15):
        dt = now + timedelta(days=offset)
        day_name = DAYS_RU[dt.weekday()]
        label = ""
        if offset == 1:
            label = " (ЗАВТРА)"
        elif offset == 2:
            label = " (ПОСЛЕЗАВТРА)"
        elif offset == 7:
            label = " (ЧЕРЕЗ НЕДЕЛЮ)"
        lines.append(f"- {day_name}{label}: {dt.strftime('%Y-%m-%d')}")
    return "\n".join(lines)


def build_active_tasks_context(active_items: Optional[List[Dict[str, Any]]]) -> str:
    if not active_items:
        return "Сейчас активных записей в базе нет."
    lines = []
    for it in active_items[:20]:
        d_str = it.get("parsed_date") or "без даты"
        t_str = it.get("parsed_time") or "без времени"
        lines.append(
            f"- ID={it['id']} | тип={it['intent']} | текст=\"{it['action']}\" | дата={d_str} | время={t_str}"
        )
    return "\n".join(lines)


def build_system_prompt(now: datetime, active_items: Optional[List[Dict[str, Any]]] = None) -> str:
    today_str = now.strftime("%Y-%m-%d")
    weekday_str = DAYS_RU[now.weekday()]
    now_time_str = now.strftime("%H:%M")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    calendar_sheet = build_calendar_cheat_sheet(now)
    tasks_context = build_active_tasks_context(active_items)

    days_until_sunday = 6 - now.weekday()
    end_of_week_str = (now + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")

    return f"""Ты системный парсер голосовых запросов ассистента «Ворона».
Сегодня {today_str} ({weekday_str}), сейчас {now_time_str}. Вчера было {yesterday_str}, завтра будет {tomorrow_str}.
Конец текущей недели (воскресенье): {end_of_week_str}.

Календарь на ближайшие дни для точного расчета дней недели:
{calendar_sheet}

Текущие активные записи пользователя в базе данных (используй их для поиска, переноса, изменения, выполнения и удаления):
{tasks_context}

Верни ТОЛЬКО валидный JSON-объект со следующими ключами:
{{
  "operation": "create" | "update" | "list_period" | "search" | "delete" | "complete" | "clarify" | "none",
  "target_id": integer | null,
  "intent": "Task" | "Reminder" | "Meeting" | null,
  "action": string | null,
  "new_action": string | null,
  "date": "YYYY-MM-DD" | null,
  "end_date": "YYYY-MM-DD" | null,
  "time": "HH:MM" | null,
  "search_query": string | null
}}
Запрещено писать любой другой текст, пояснения и markdown.

ПРАВИЛА ВЫБОРА OPERATION:
1. "create": пользователь добавляет НОВУЮ задачу, напоминание или встречу («купить молоко», «напомни выпить таблетки в 20:00», «встреча с Анной завтра в 10 утра»).
2. "update": пользователь просит ПЕРЕНЕСТИ, ИЗМЕНИТЬ, ПОМЕНЯТЬ, СДВИНУТЬ, ОТЛОЖИТЬ, ПЕРЕИМЕНОВАТЬ или ИСПРАВИТЬ уже существующую задачу, напоминание или встречу!
   Примеры "update":
   - Перенос даты/времени: «перенеси встречу с преподом на завтра в 15:00», «сдвинь напоминание про таблетки на 21:00», «поменяй время стоматолога на 18:00», «отложи задачу купить молоко на послезавтра».
     * В "target_id" укажи ID найденной записи из списка выше (или null, если не уверен).
     * В "search_query" укажи старое название записи (например: "Встреча с преподом", "таблетки", "стоматолог", "купить молоко").
     * В "new_action" и "action" ОБЯЗАТЕЛЬНО поставь null (так как сам текст дела НЕ менялся, менялись только дата/время)!
     * В "date" укажи новую дату YYYY-MM-DD (если менялась дата, иначе null), в "time" — новое время HH:MM (если менялось время, иначе null).
   - Изменение текста (переименование): «измени задачу купить молоко на купить кефир», «поменяй напоминание позвонить маме на позвонить бабушке завтра в 10:00», «переименуй встречу с преподом в консультацию».
     * В "target_id" укажи ID найденной записи из списка выше.
     * В "search_query" укажи старое название записи ("купить молоко", "позвонить маме", "встреча с преподом").
     * В "new_action" укажи НОВЫЙ текст записи с заглавной буквы без даты и времени ("Купить кефир", "Позвонить бабушке", "Консультация").
     * Если также названы новые дата или время — укажи их в "date" и "time", иначе null.
3. "list_period": пользователь спрашивает о планах на период («Что у меня сегодня?», «Какие планы на завтра?», «Какие напоминания на сегодня?», «Что запланировано на эту неделю?»).
   - Укажи начало периода в "date" и конец периода в "end_date".
4. "search": пользователь ищет старую запись («Найди задачу про презентацию», «Когда у меня была встреча с Иваном?»). Положи тему в "search_query".
5. "delete": пользователь просит удалить или отменить запись («Удали задачу про молоко», «Убери встречу с дизайнером»). Положи ID в "target_id" и тему в "search_query".
6. "complete": пользователь просит отметить запись выполненной («Отметь задачу про молоко выполненной», «Заверши задачу купить хлеб»). Положи ID в "target_id" и тему в "search_query".
7. "clarify": если запрос неоднозначен. Положи текст уточняющего вопроса в "action".
8. "none": если в тексте нет смысла, только шум или названа только дата без дела («завтра»).

ПРАВИЛА РАЗДЕЛЕНИЯ НА 3 ТИПА (INTENT: "Task" | "Reminder" | "Meeting"):
1. "Meeting" (Встреча): если речь о встрече, созвоне, обеде с кем-то, приёме у врача/стоматолога, планёрке, консультации или событии с другими людьми.
2. "Reminder" (Напоминание): если пользователь явно использует слова «напомни», «напоминание», «напоминалка», «не забыть».
3. "Task" (Задача): все остальные дела, поручения, покупки и задачи.

ПРАВИЛА ДЛЯ ПОЛЕЙ ACTION, DATE, TIME:
1. action (для "create"): суть дела с заглавной буквы короткой фразой без даты, точного времени и без слов «поставь напоминание», «напомни», «запиши задачу».
2. date: строго YYYY-MM-DD от {today_str}. Если названный день недели совпадает с сегодняшним ({weekday_str}), бери ближайшую БУДУЩУЮ дату (через 7 дней).
3. time: строго HH:MM (24 часа). «В три часа дня» -> "15:00", «в полдень» -> "12:00", «в половине третьего» -> "14:30".
4. Если при создании ("create") названо только точное время без даты: если сегодня это время еще НЕ прошло (> {now_time_str}) — ставь {today_str}, иначе {tomorrow_str}.
"""
