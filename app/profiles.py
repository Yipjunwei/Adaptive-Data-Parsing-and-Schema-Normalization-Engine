from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROFILE_STORE = Path(__file__).parent.parent / "data" / "profiles.json"


CANONICAL_FIELDS = {
    "timestamp",
    "tool_id",
    "chamber_id",
    "temperature_c",
    "pressure_pa",
    "error_code",
    "severity",
    "raw_message",
    "event_type",
    "sensor_id",
    "status",
}


def _clean_key(key: str) -> str:
    return (
        str(key)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _source_fingerprint(format_detected: str, raw_payload: dict[str, Any]) -> str:
    keys = sorted(_clean_key(k) for k in raw_payload.keys())
    # fingerprint based on format + stable key shape
    return f"{format_detected}|{'|'.join(keys[:30])}"


def _infer_structure_traits(raw_payload: dict[str, Any]) -> dict[str, Any]:
    keys = [_clean_key(k) for k in raw_payload.keys()]

    nested_key_count = sum(1 for k in keys if "_" in k)
    max_depth = max((len(k.split("_")) for k in keys), default=1)

    traits = {
        "key_count": len(keys),
        "nested_key_count": nested_key_count,
        "max_depth": max_depth,
        "has_events_branch": any("event" in k for k in keys),
        "has_metadata_branch": any("metadata" in k for k in keys),
        "has_system_branch": any("system" in k for k in keys),
    }
    return traits


def _build_key_map(raw_payload: dict[str, Any], normalized_payload: dict[str, Any]) -> dict[str, str]:
    """
    Safer raw_key -> canonical_key learning.

    We only store mappings when there is a plausible semantic match.
    """
    key_map: dict[str, str] = {}
    normalized_keys = set(normalized_payload.keys()) & CANONICAL_FIELDS

    for raw_key in raw_payload.keys():
        cleaned = _clean_key(raw_key)
        tokens = set(cleaned.split("_"))

        for canonical in normalized_keys:
            canonical_tokens = set(canonical.split("_"))

            # exact match
            if cleaned == canonical:
                key_map[cleaned] = canonical
                break

            # suffix match
            if cleaned.endswith("_" + canonical):
                key_map[cleaned] = canonical
                break

            # token overlap
            overlap = tokens & canonical_tokens
            if overlap:
                # avoid weak overlap on generic tokens only
                meaningful = overlap - {"id", "raw"}
                if meaningful:
                    key_map[cleaned] = canonical
                    break

    return key_map


@dataclass
class SourceProfile:
    profile_id: str
    fingerprint: str
    format_detected: str
    sample_keys: list[str]
    structure_traits: dict[str, Any]
    key_map: dict[str, str] = field(default_factory=dict)
    preferred_focus_section: str | None = None
    preferred_event_type: str | None = None
    confidence_avg: float = 0.0
    successful_parses: int = 0
    gemini_uses: int = 0
    last_summary: str | None = None


_PROFILES: dict[str, SourceProfile] = {}


def init_profiles() -> None:
    PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)

    if not PROFILE_STORE.exists():
        return

    try:
        data = json.loads(PROFILE_STORE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return

        _PROFILES.clear()
        for item in data:
            try:
                profile = SourceProfile(**item)
                _PROFILES[profile.fingerprint] = profile
            except Exception:
                continue
    except Exception:
        # fail soft
        return


def _save_profiles() -> None:
    PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(p) for p in _PROFILES.values()]
    PROFILE_STORE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def list_profiles() -> list[dict[str, Any]]:
    return [asdict(p) for p in _PROFILES.values()]


def lookup_profile(format_detected: str, raw_payload: dict[str, Any]) -> SourceProfile | None:
    fingerprint = _source_fingerprint(format_detected, raw_payload)
    direct = _PROFILES.get(fingerprint)
    if direct:
        return direct

    # fallback: fuzzy-ish structural lookup
    incoming_traits = _infer_structure_traits(raw_payload)
    incoming_keys = set(_clean_key(k) for k in raw_payload.keys())

    best_match: SourceProfile | None = None
    best_score = 0.0

    for profile in _PROFILES.values():
        if profile.format_detected != format_detected:
            continue

        sample_keys = set(profile.sample_keys)
        if not sample_keys:
            continue

        key_overlap = len(incoming_keys & sample_keys) / max(len(sample_keys), 1)

        trait_score = 0.0
        if profile.structure_traits.get("has_events_branch") == incoming_traits.get("has_events_branch"):
            trait_score += 0.2
        if profile.structure_traits.get("has_metadata_branch") == incoming_traits.get("has_metadata_branch"):
            trait_score += 0.1
        if profile.structure_traits.get("has_system_branch") == incoming_traits.get("has_system_branch"):
            trait_score += 0.1
        if abs(profile.structure_traits.get("max_depth", 1) - incoming_traits.get("max_depth", 1)) <= 1:
            trait_score += 0.1

        score = key_overlap + trait_score

        if score > best_score and score >= 0.55:
            best_score = score
            best_match = profile

    return best_match


def promote_profile(
    format_detected: str,
    raw_payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    confidence: float,
    used_gemini: bool,
    summary: str | None = None,
    focus_section: str | None = None,
) -> SourceProfile | None:
    """
    Create or update a source profile when parsing quality is good enough.
    """
    if confidence < 0.72:
        return None

    fingerprint = _source_fingerprint(format_detected, raw_payload)
    existing = _PROFILES.get(fingerprint)

    key_map = _build_key_map(raw_payload, normalized_payload)
    structure_traits = _infer_structure_traits(raw_payload)
    sample_keys = sorted(_clean_key(k) for k in raw_payload.keys())

    preferred_event_type = normalized_payload.get("event_type")
    if preferred_event_type == "unknown_event":
        preferred_event_type = None

    if existing is None:
        profile = SourceProfile(
            profile_id=f"profile_{len(_PROFILES) + 1}",
            fingerprint=fingerprint,
            format_detected=format_detected,
            sample_keys=sample_keys,
            structure_traits=structure_traits,
            key_map=key_map,
            preferred_focus_section=focus_section,
            preferred_event_type=preferred_event_type,
            confidence_avg=confidence,
            successful_parses=1,
            gemini_uses=1 if used_gemini else 0,
            last_summary=summary,
        )
        _PROFILES[fingerprint] = profile
    else:
        existing.sample_keys = sorted(set(existing.sample_keys) | set(sample_keys))
        existing.structure_traits = structure_traits
        existing.key_map.update(key_map)

        total = existing.successful_parses + 1
        existing.confidence_avg = round(
            ((existing.confidence_avg * existing.successful_parses) + confidence) / total,
            3,
        )
        existing.successful_parses = total

        if used_gemini:
            existing.gemini_uses += 1

        if focus_section:
            existing.preferred_focus_section = focus_section

        if preferred_event_type:
            existing.preferred_event_type = preferred_event_type

        if summary:
            existing.last_summary = summary

        profile = existing

    _save_profiles()
    return profile