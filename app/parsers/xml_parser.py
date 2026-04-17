from __future__ import annotations

from typing import Any

import xmltodict

from app.parsers.base import BaseParser


class XMLParser(BaseParser):
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
        data = xmltodict.parse(content)
        root = next(iter(data.values()), {})

        metadata = root.get("metadata", {})
        system = root.get("system", {})
        events = root.get("events", {}).get("event", [])

        if isinstance(events, dict):
            events = [events]

        primary_event = events[0] if events else {}

        combined = {
            "metadata": metadata,
            "event": primary_event,
            "system": system,
        }

        return self._flatten_dict(combined)

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