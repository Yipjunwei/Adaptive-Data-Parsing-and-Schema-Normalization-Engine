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
    return str(key).strip().lower().replace(" ", "_").replace("-", "_")


def _source_fingerprint(format_detected: str, raw_payload: dict[str, Any]) -> str:
    keys = sorted(_clean_key(k) for k in raw_payload.keys())
    return f"{format_detected}|{'|'.join(keys[:40])}"


def _infer_structure_traits(raw_payload: dict[str, Any]) -> dict[str, Any]:
    keys = [_clean_key(k) for k in raw_payload.keys()]

    return {
        "key_count": len(keys),
        "nested_key_count": sum(1 for k in keys if "_" in k),
        "max_depth": max((len(k.split("_")) for k in keys), default=1),
        "has_events_branch": any("event" in k for k in keys),
        "has_metadata_branch": any("metadata" in k for k in keys),
        "has_system_branch": any("system" in k for k in keys),
        "has_sensor_branch": any("sensor" in k for k in keys),
    }


def _build_key_map(raw_payload: dict[str, Any], normalized_payload: dict[str, Any]) -> dict[str, str]:
    key_map: dict[str, str] = {}
    normalized_keys = set(normalized_payload.keys()) & CANONICAL_FIELDS

    for raw_key in raw_payload.keys():
        cleaned = _clean_key(raw_key)
        tokens = set(cleaned.split("_"))

        for canonical in normalized_keys:
            canonical_tokens = set(canonical.split("_"))

            if cleaned == canonical:
                key_map[cleaned] = canonical
                break

            if cleaned.endswith("_" + canonical):
                key_map[cleaned] = canonical
                break

            overlap = tokens & canonical_tokens
            meaningful = overlap - {"id", "raw"}
            if meaningful:
                key_map[cleaned] = canonical
                break

    return key_map


def _guess_decoder_name(
    format_detected: str,
    raw_payload: dict[str, Any],
    vendor_label: str | None = None,
) -> str | None:
    low_vendor = (vendor_label or "").lower()

    if format_detected == "bin":
        return "generic_binary_decoder"

    if "vendor_a" in low_vendor and format_detected == "json":
        return "vendor_a_json_decoder"

    if "vendor_b" in low_vendor and format_detected == "json":
        return "vendor_b_json_decoder"

    if format_detected == "xml" and any("recipe" in _clean_key(k) for k in raw_payload.keys()):
        return "recipe_xml_decoder"

    return None


@dataclass
class SourceProfile:
    profile_id: str
    fingerprint: str
    format_detected: str
    vendor_label: str | None = None
    decoder_name: str | None = None
    sample_keys: list[str] = field(default_factory=list)
    structure_traits: dict[str, Any] = field(default_factory=dict)
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
                _PROFILES[profile.profile_id] = profile
            except Exception:
                continue
    except Exception:
        return


def _save_profiles() -> None:
    PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(p) for p in _PROFILES.values()]
    PROFILE_STORE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def list_profiles() -> list[dict[str, Any]]:
    return [asdict(p) for p in _PROFILES.values()]


def lookup_profile(
    format_detected: str,
    raw_payload: dict[str, Any],
    vendor_label: str | None = None,
) -> SourceProfile | None:
    fingerprint = _source_fingerprint(format_detected, raw_payload)

    # 1. direct vendor-label match
    if vendor_label:
        low_vendor = vendor_label.lower().strip()
        for profile in _PROFILES.values():
            if (
                profile.vendor_label
                and profile.vendor_label.lower().strip() == low_vendor
                and profile.format_detected == format_detected
            ):
                return profile

    # 2. exact fingerprint match
    for profile in _PROFILES.values():
        if profile.fingerprint == fingerprint and profile.format_detected == format_detected:
            return profile

    # 3. fuzzy structural match
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

        # Jaccard similarity: intersection / union.
        # Prevents large payloads from accidentally scoring high against
        # any stored profile just because they share a few common key names.
        intersection = len(incoming_keys & sample_keys)
        union = len(incoming_keys | sample_keys)
        key_jaccard = intersection / max(union, 1)

        # Require at least 3 keys to actually overlap — coincidental 1-2 key
        # matches (e.g. both have "timestamp") should not trigger a profile hit.
        if intersection < 3:
            continue

        # Trait score: only award points for shared POSITIVE traits (both True).
        # Matching False==False (e.g. neither has an events branch) tells us
        # nothing about whether they are the same source type.
        trait_score = 0.0
        for trait in ("has_events_branch", "has_metadata_branch", "has_system_branch", "has_sensor_branch"):
            if incoming_traits.get(trait) and profile.structure_traits.get(trait):
                trait_score += 0.1
        if abs(profile.structure_traits.get("max_depth", 1) - incoming_traits.get("max_depth", 1)) <= 1:
            trait_score += 0.05

        # key_jaccard is the primary signal (max 1.0); trait_score is a tiebreaker (max 0.45)
        score = key_jaccard + trait_score

        # Raised threshold: require genuinely strong key overlap to claim a profile hit
        if score > best_score and score >= 0.70:
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
    vendor_label: str | None = None,
) -> SourceProfile | None:
    if confidence < 0.72:
        return None

    fingerprint = _source_fingerprint(format_detected, raw_payload)
    existing = lookup_profile(format_detected, raw_payload, vendor_label=vendor_label)

    key_map = _build_key_map(raw_payload, normalized_payload)
    structure_traits = _infer_structure_traits(raw_payload)
    sample_keys = sorted(_clean_key(k) for k in raw_payload.keys())

    preferred_event_type = normalized_payload.get("event_type")
    if preferred_event_type == "unknown_event":
        preferred_event_type = None

    decoder_name = _guess_decoder_name(format_detected, raw_payload, vendor_label)

    if existing is None:
        profile = SourceProfile(
            profile_id=f"profile_{len(_PROFILES) + 1}",
            fingerprint=fingerprint,
            format_detected=format_detected,
            vendor_label=vendor_label,
            decoder_name=decoder_name,
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
        _PROFILES[profile.profile_id] = profile
    else:
        existing.fingerprint = fingerprint
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

        if vendor_label:
            existing.vendor_label = vendor_label

        if decoder_name:
            existing.decoder_name = decoder_name

        if focus_section:
            existing.preferred_focus_section = focus_section

        if preferred_event_type:
            existing.preferred_event_type = preferred_event_type

        if summary:
            existing.last_summary = summary

        profile = existing

    _save_profiles()
    return profile


def build_profile_guidance(profile) -> dict[str, Any]:
    guidance: dict[str, Any] = {}

    if getattr(profile, "preferred_focus_section", None):
        guidance["focus_section"] = profile.preferred_focus_section

    if getattr(profile, "decoder_name", None) == "generic_binary_decoder":
        guidance["vendor_decoder"] = "demo_v1"

    if getattr(profile, "decoder_name", None):
        guidance["decoder_name"] = profile.decoder_name

    if getattr(profile, "vendor_label", None):
        guidance["vendor_label"] = profile.vendor_label

    return guidance