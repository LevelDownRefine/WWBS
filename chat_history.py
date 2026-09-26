"""Bounded, local per-character chat history; never stores connection credentials."""
import json
from pathlib import Path


class ChatHistory:
    def __init__(self, path: Path):
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.records = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.records = {}

    def messages(self, pet_id: str) -> list[dict]:
        items = self.records.get(pet_id, [])
        if not isinstance(items, list):
            return []
        return [item for item in items[-500:] if isinstance(item, dict)
                and isinstance(item.get("speaker"), str) and isinstance(item.get("text"), str)]

    def append(self, pet_id: str, speaker: str, text: str) -> None:
        self.records[pet_id] = (self.messages(pet_id) + [{"speaker": speaker, "text": text}])[-500:]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
