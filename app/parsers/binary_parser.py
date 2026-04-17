from __future__ import annotations

import base64
import binascii
import re
import struct
from typing import Any

from app.parsers.base import BaseParser


class BinaryParser(BaseParser):
    """
    Generic binary log parser.

    Strategy:
    1. Try vendor-specific decoding if guidance/vendor profile provides one.
    2. Try to extract printable ASCII fragments from the byte stream.
    3. Try simple fixed-offset decoding for known demo formats.
    4. Fall back to hex/base64 payload for LLM-assisted interpretation.
    """

    def parse(self, content: bytes | str, guidance: dict | None = None) -> dict[str, Any]:
        if isinstance(content, str):
            raw = content.encode("utf-8", errors="ignore")
        else:
            raw = content

        guidance = guidance or {}

        # 1. optional vendor-specific decoder
        vendor_decoder = guidance.get("vendor_decoder")
        if vendor_decoder == "demo_v1":
            parsed = self._parse_demo_v1(raw)
            if parsed:
                return parsed

        # 2. extract printable text fragments
        ascii_fragments = self._extract_ascii_fragments(raw)

        extracted: dict[str, Any] = {
            "binary_size_bytes": len(raw),
            "hex_preview": binascii.hexlify(raw[:64]).decode("ascii"),
            "base64_preview": base64.b64encode(raw[:64]).decode("ascii"),
        }

        if ascii_fragments:
            extracted["ascii_fragments"] = ascii_fragments[:10]

            joined = " | ".join(ascii_fragments).lower()
            if "vac" in joined:
                extracted["event_type"] = "vacuum pressure low"
            elif "temp" in joined or "heat" in joined:
                extracted["event_type"] = "temperature high"

            alarm_match = re.search(r"alarm[:=\s]+([A-Za-z0-9_-]+)", joined, re.IGNORECASE)
            if alarm_match:
                extracted["alarm"] = alarm_match.group(1)

            tool_match = re.search(r"tool[:=\s]+([A-Za-z0-9_-]+)", joined, re.IGNORECASE)
            if tool_match:
                extracted["tool"] = tool_match.group(1)

            chamber_match = re.search(r"chamber[:=\s]+([A-Za-z0-9_-]+)", joined, re.IGNORECASE)
            if chamber_match:
                extracted["chamber"] = chamber_match.group(1)

        return extracted

    def _extract_ascii_fragments(self, raw: bytes) -> list[str]:
        text = "".join(chr(b) if 32 <= b <= 126 else " " for b in raw)
        return [frag.strip() for frag in text.split("  ") if frag.strip()]

    def _parse_demo_v1(self, raw: bytes) -> dict[str, Any]:
        """
        Example fixed-layout decoder for synthetic binary logs only.
        Layout example:
        - 4 bytes magic
        - 8 bytes unix timestamp (unsigned long long)
        - 4 bytes float temperature
        - 4 bytes float pressure
        - 2 bytes chamber id
        - remaining bytes ascii message
        """
        if len(raw) < 22:
            return {}

        try:
            magic = raw[:4]
            if magic != b"LOG1":
                return {}

            timestamp = struct.unpack(">Q", raw[4:12])[0]
            temperature = struct.unpack(">f", raw[12:16])[0]
            pressure = struct.unpack(">f", raw[16:20])[0]
            chamber_id = struct.unpack(">H", raw[20:22])[0]
            message = raw[22:].decode("utf-8", errors="ignore").strip("\x00 ")

            return {
                "timestamp": timestamp,
                "temperature_c": round(temperature, 3),
                "pressure_pa": round(pressure, 3),
                "chamber_id": chamber_id,
                "raw_message": message,
            }
        except Exception:
            return {}