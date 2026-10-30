from typing import List, Dict


class MemoryManager:
    """Управление краткосрочной памятью диалога в ОЗУ."""

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: List[Dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history * 2:]

    def get_messages(self) -> List[Dict[str, str]]:
        return list(self.history)

    def clear(self) -> None:
        self.history.clear()
