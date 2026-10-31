from __future__ import annotations

from pathlib import Path
from typing import Any

from .repository import EquipmentRepository


class CharacterService:
    def __init__(self, db_path: Path):
        self.repository=EquipmentRepository(db_path)

    def equipment(self) -> list[dict[str, Any]]:
        return self.repository.list_equipment()
