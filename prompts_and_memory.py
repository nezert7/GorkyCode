import datetime
from typing import List, Dict


class MemoryManager:
    """Управление краткосрочной памятью диалога."""
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: List[Dict[str, str]] = []

    def add_message(self, role: str, content: str):
        """Добавляет сообщение в историю."""
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history * 2:]

    def get_messages(self) -> List[Dict[str, str]]:
        """Возвращает текущую историю диалога."""
        return list(self.history)

    def clear(self):
        """Очищает историю диалога."""
        self.history.clear()


def build_system_prompt() -> str:
    """Генерирует системный промпт с точной текущей датой и временем."""
    now = datetime.datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %H:%M (%A)")

    return (
        f"Ты — умный локальный голосовой ассистент для управления задачами и встречами.\n"
        f"Текущее локальное время и дата: {current_time_str}.\n\n"
        f"Твои обязанности:\n"
        f"1. Помогать пользователю создавать, находить, редактировать и удалять задачи и встречи.\n"
        f"2. Использовать доступные инструменты (tools/functions) для взаимодействия с базой данных.\n"
        f"3. Анализировать возможные накладки и конфликты во времени перед добавлением событий.\n"
        f"4. Отвечать лаконично и естественно, так как твои ответы будут озвучены голосом.\n"
        f"5. Если пользователь просит создать встречу на относительное время ('завтра в 15:00'), "
        f"вычисляй точную дату отталкиваясь от текущей: {current_time_str}."
    )

