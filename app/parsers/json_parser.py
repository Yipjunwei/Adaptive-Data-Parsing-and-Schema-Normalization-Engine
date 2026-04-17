from __future__ import annotations

import json
from typing import Any

from app.parsers.base import BaseParser


class JSONParser(BaseParser):
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
        data = json.loads(content)
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return {"raw": str(data)}
        return self._flatten_dict(data)

    def _flatten_dict(self, data: Any, prefix: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {}

        if isinstance(data, dict):
            for key, value in data.items():
                clean_key = str(key).replace("@", "").replace("#text", "text")
                next_prefix = f"{prefix}_{clean_key}" if prefix else clean_key
                out.update(self._flatten_dict(value, next_prefix))

        elif isinstance(data, list):
            if data:
                out.update(self._flatten_dict(data[0], prefix))

        else:
            out[prefix] = data

        return out