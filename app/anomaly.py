from __future__ import annotations

from typing import Any


def anomaly_score(logs: list[dict[str, Any]]) -> dict[str, Any]:
    features = []
    ids = []

    for log in logs:
        payload = log.get("payload", {})
        temp = float(payload.get("temperature_c", 0) or 0)
        pressure = float(payload.get("pressure_pa", 0) or 0)
        sev = payload.get("severity", "medium")
        sev_num = {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(str(sev).lower(), 1)
        features.append([temp, pressure, sev_num])
        ids.append(log["id"])

    if not features:
        return {"available": True, "anomalies": []}

    try:
        from sklearn.ensemble import IsolationForest
    except Exception:
        return {
            "available": False,
            "message": "scikit-learn not installed; anomaly check skipped.",
            "anomalies": [],
        }

    model = IsolationForest(contamination=0.2, random_state=42)
    preds = model.fit_predict(features)
    scores = model.decision_function(features)

    anomalies = []
    for log_id, pred, score in zip(ids, preds, scores):
        if pred == -1:
            anomalies.append({"log_id": log_id, "score": float(round(score, 4))})

    return {"available": True, "anomalies": anomalies}
