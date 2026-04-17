from __future__ import annotations

import csv
import io
import statistics
from typing import Any

from app.parsers.base import BaseParser

# Canonical sensor columns we want to summarise numerically
_NUMERIC_CANONICAL = {
    "temperature_c", "pressure_pa", "temperature", "temp", "pressure",
    "rf_power", "rf_power_w", "flow", "flow_rate", "voltage", "current",
    "humidity", "speed", "rpm",
}

# How many rows to keep as representative samples in the output
_MAX_SAMPLE_ROWS = 3

# Minimum fraction of rows that must be non-null for a column to get stats
_MIN_FILL_RATIO = 0.5


def _is_numeric_col(header: str) -> bool:
    """Heuristic: is this column likely to contain sensor readings?"""
    h = header.strip().lower().replace(" ", "_").replace("-", "_")
    if h in _NUMERIC_CANONICAL:
        return True
    for token in ("temp", "press", "power", "flow", "volt", "current", "rpm", "speed", "humidity"):
        if token in h:
            return True
    return False


def _try_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


class CSVParser(BaseParser):
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        if not rows:
            return {}

        headers = list(rows[0].keys())
        total_rows = len(rows)

        # ------------------------------------------------------------------
        # Single-row CSV — return as before (no summarisation needed)
        # ------------------------------------------------------------------
        if total_rows == 1:
            return {str(k): v for k, v in rows[0].items()}

        # ------------------------------------------------------------------
        # Multi-row CSV — produce a summary payload
        # ------------------------------------------------------------------
        result: dict[str, Any] = {
            "row_count": total_rows,
        }

        # Pull the first row's non-numeric identifiers (tool, chamber, timestamp…)
        first = rows[0]
        for k, v in first.items():
            if v and not _is_numeric_col(k):
                result[str(k).strip()] = v

        # ------------------------------------------------------------------
        # Numeric column statistics
        # ------------------------------------------------------------------
        numeric_stats: dict[str, Any] = {}
        spike_flags: list[str] = []

        for header in headers:
            if not _is_numeric_col(header):
                continue

            values = [_try_float(r[header]) for r in rows if header in r]
            values = [v for v in values if v is not None]

            if len(values) / total_rows < _MIN_FILL_RATIO:
                continue  # too sparse to be meaningful

            col_min = min(values)
            col_max = max(values)
            col_mean = statistics.mean(values)
            col_std = statistics.stdev(values) if len(values) > 1 else 0.0

            canonical = header.strip().lower().replace(" ", "_").replace("-", "_")
            numeric_stats[canonical] = {
                "min": round(col_min, 4),
                "max": round(col_max, 4),
                "mean": round(col_mean, 4),
                "std": round(col_std, 4),
                "samples": len(values),
            }

            # Spike detection: flag if any value is >3 std deviations from mean
            if col_std > 0:
                for v in values:
                    if abs(v - col_mean) > 3 * col_std:
                        spike_flags.append(canonical)
                        break

            # Also expose the representative scalar value (mean) directly so
            # schema_mapper can pick it up for event_type / confidence scoring
            if canonical in _NUMERIC_CANONICAL:
                result.setdefault(canonical, round(col_mean, 4))

        if numeric_stats:
            result["sensor_summary"] = numeric_stats

        if spike_flags:
            result["spike_detected_columns"] = spike_flags

        # ------------------------------------------------------------------
        # Sample rows — preserve a few raw rows for LLM context if needed
        # ------------------------------------------------------------------
        sample_indices = _pick_sample_indices(rows, spike_flags, headers)
        result["sample_rows"] = [
            {str(k): v for k, v in rows[i].items()} for i in sample_indices
        ]

        return result


def _pick_sample_indices(
    rows: list[dict],
    spike_flags: list[str],
    headers: list[str],
) -> list[int]:
    """
    Return up to _MAX_SAMPLE_ROWS indices:
    - always include row 0 (first)
    - include the row with the max value for the first spiking column (if any)
    - include the last row
    """
    n = len(rows)
    indices: list[int] = [0]

    if spike_flags:
        spike_col = spike_flags[0]
        best_idx = 0
        best_val = None
        for i, row in enumerate(rows):
            v = _try_float(row.get(spike_col, ""))
            if v is not None and (best_val is None or v > best_val):
                best_val = v
                best_idx = i
        if best_idx not in indices:
            indices.append(best_idx)

    if n - 1 not in indices:
        indices.append(n - 1)

    return sorted(indices[:_MAX_SAMPLE_ROWS])