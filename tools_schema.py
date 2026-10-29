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

Текущие активные записи пользователя в базе данных:
{tasks_context}

Верни ТОЛЬКО валидный JSON-объект со следующими ключами:
{{
  "operation": "create" | "clarify" | "update" | "list_period" | "search" | "delete" | "complete" | "none",
  "target_id": integer | null,
  "intent": "Task" | "Reminder" | "Meeting" | null,
  "action": string | null,
  "new_action": string | null,
  "date": "YYYY-MM-DD" | null,
  "end_date": "YYYY-MM-DD" | null,
  "time": "HH:MM" | null,
  "search_query": string | null,
  "question": string | null
}}
Запрещено писать любой другой текст, пояснения и markdown.

ПРАВИЛА ВЫБОРА OPERATION:
1. "create": пользователь создаёт событие и ЯВНО назвал все 3 элемента: название события (action), дату (date) и точное время (time).
2. "clarify": пользователь хочет создать событие, но НЕ НАЗВАЛ хотя бы один из 3 элементов: дату, точное время или название события.
   - Заполни те поля ("action", "date", "time", "intent"), которые есть в тексте, а неизвестные оставь null.
   - В поле "question" напиши короткий уточняющий вопрос (например: "Уточните время.", "Уточните дату и время.", "Какое событие запланировать?").
   - СТРОГО ЗАПРЕЩЕНО писать текст вопроса в поле "action"! В "action" всегда пиши только суть события (или null, если название события еще не сказано).
3. "update": пользователь просит перенести или изменить уже существующую запись в базе.
4. "list_period": вопрос о планах на период.
5. "search": поиск старой записи.
6. "delete": удаление существующей записи.
7. "complete": отметка существующей записи выполненной.
8. "none": если в тексте только шум или бессмысленные междометия.

ПРАВИЛА РАЗДЕЛЕНИЯ НА 3 ТИПА (INTENT: "Task" | "Reminder" | "Meeting"):
1. "Meeting": встречи, созвоны, обед с кем-то, приём у врача/стоматолога, планёрки, консультации.
2. "Reminder": если есть слова «напомни», «напоминание», «напоминалка», «не забыть».
3. "Task": все остальные дела, покупки и задачи.

ПРАВИЛА ДЛЯ ПОЛЕЙ ACTION, DATE, TIME:
1. action: только суть события с заглавной буквы короткой фразой без даты, времени и без слов «поставь напоминание», «напомни», «запиши задачу», «ну», «короче». Если сказаны только дата или время без названия дела («завтра в 15:00»), верни "action": null.
2. date: строго YYYY-MM-DD от {today_str}. Если пользователь НЕ назвал дату (например, сказал только «позвонить маме в 15:00»), верни "date": null! Не подставляй сегодняшнюю дату сам.
3. time: строго HH:MM (24 часа). «В три часа дня» -> "15:00", «в полдень» -> "12:00", «в половине третьего» -> "14:30". Если точное время не названо (или сказано размыто «утром», «вечером»), верни "time": null.
4. Если в тексте объединены две реплики (исходная запись и дозапись), собери из них единое событие: возьми название, дату и время из обеих частей.
"""