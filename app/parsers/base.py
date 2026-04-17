from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    @abstractmethod
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
        raise NotImplementedError