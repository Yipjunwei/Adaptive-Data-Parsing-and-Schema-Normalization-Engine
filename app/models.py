from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestResult(BaseModel):
    format_detected: str
    raw_payload: dict[str, Any]
    normalized_payload: dict[str, Any]
    confidence: float
    needs_review: bool
    explanation: str


class FeedbackRule(BaseModel):
    raw_key: str = Field(..., min_length=1)
    canonical_key: str = Field(..., min_length=1)


class StoredLog(BaseModel):
    id: int
    format_detected: str
    confidence: float
    needs_review: bool
    payload: dict[str, Any]
    explanation: str
    created_at: str
