from __future__ import annotations

from typing import Any

from app.parsers import ParserFactory


def parse_content(content: str, detected_format: str, guidance: dict | None = None) -> dict[str, Any]:
    parser = ParserFactory.get_parser(detected_format)
    return parser.parse(content, guidance=guidance)