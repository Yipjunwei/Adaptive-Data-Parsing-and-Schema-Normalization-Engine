from __future__ import annotations

import csv
import io
from typing import Any

from app.parsers.base import BaseParser


class CSVParser(BaseParser):
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(content))
        row = next(reader, None)
        if row is None:
            return {}
        return {str(k): v for k, v in row.items()}