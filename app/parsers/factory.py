from __future__ import annotations

from app.parsers.base import BaseParser
from app.parsers.csv_parser import CSVParser
from app.parsers.json_parser import JSONParser
from app.parsers.text_parser import TextParser
from app.parsers.xml_parser import XMLParser


class ParserFactory:
    @staticmethod
    def get_parser(format_type: str) -> BaseParser:
        format_type = format_type.lower().strip()

        if format_type == "json":
            return JSONParser()
        if format_type == "xml":
            return XMLParser()
        if format_type == "csv":
            return CSVParser()
        return TextParser()