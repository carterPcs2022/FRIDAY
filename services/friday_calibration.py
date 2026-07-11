"""services/friday_calibration.py — tracks how well FRIDAY's probability
calls (the "what are the odds" / PROBABILITY_TRIGGERS responses in
server.py) actually pan out, so calibration can be checked against
reality instead of just sounding confident.

Persists to memory/friday_calibration.json, following the same
load/save-with-mkdir pattern as services/friday_calendar.py's TOKEN_FILE
handling — a flat JSON file is enough here, there's no concurrent-writer
problem this needs to solve beyond what that pattern already covers.
"""
import json
import uuid
from pathlib import Path
from datetime import datetime

CALIBRATION_FILE = Path("memory/friday_calibration.json")


class CalibrationTracker:

    def _load(self) -> list:
        if CALIBRATION_FILE.exists():
            try:
                return json.loads(CALIBRATION_FILE.read_text())
            except Exception:
                return []
        return []

    def _save(self, predictions: list):
        CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_FILE.write_text(json.dumps(predictions, indent=2))

    def log_prediction(self, question: str, probability: int, reasoning: str = "") -> dict:
        predictions = self._load()
        entry = {
            "id": uuid.uuid4().hex[:12],
            "question": question[:300],
            "probability": int(probability),
            "reasoning": reasoning[:500],
            "ts": datetime.now().isoformat(),
            "resolved": False,
            "outcome": None,
            "resolved_ts": None,
        }
        predictions.append(entry)
        self._save(predictions)
        return entry

    def resolve_prediction(self, pred_id: str, outcome: bool) -> dict:
        predictions = self._load()
        for p in predictions:
            if p["id"] == pred_id:
                p["resolved"] = True
                p["outcome"] = bool(outcome)
                p["resolved_ts"] = datetime.now().isoformat()
                self._save(predictions)
                return p
        return {"error": f"No prediction found with id {pred_id}"}

    def get_unresolved(self, days_old: int = 7) -> list:
        """Unresolved predictions at least `days_old` days old, oldest
        first — old enough that the outcome should be known by now, which
        is the useful set to nudge the user about."""
        now = datetime.now()
        out = []
        for p in self._load():
            if p.get("resolved"):
                continue
            try:
                age = (now - datetime.fromisoformat(p["ts"])).days
            except Exception:
                continue
            if age >= days_old:
                out.append(p)
        out.sort(key=lambda p: p["ts"])
        return out

    def calibration_score(self) -> dict:
        """Buckets resolved predictions by confidence (low <40, medium
        40-70, high >=70) and compares predicted average probability
        against actual hit rate per bucket. Needs at least 5 resolved
        predictions total — with fewer than that the buckets are too
        noisy to mean anything."""
        resolved = [p for p in self._load() if p.get("resolved")]
        if len(resolved) < 5:
            return {
                "enough_data": False,
                "resolved_count": len(resolved),
                "message": "Not enough resolved predictions yet, boss — need at least 5.",
            }

        buckets = {
            "low": {"label": "<40%", "preds": []},
            "medium": {"label": "40-70%", "preds": []},
            "high": {"label": ">=70%", "preds": []},
        }
        for p in resolved:
            prob = p.get("probability", 0)
            if prob < 40:
                buckets["low"]["preds"].append(p)
            elif prob <= 70:
                buckets["medium"]["preds"].append(p)
            else:
                buckets["high"]["preds"].append(p)

        result = {"enough_data": True, "resolved_count": len(resolved), "buckets": {}}
        for name, data in buckets.items():
            preds = data["preds"]
            if not preds:
                result["buckets"][name] = {
                    "label": data["label"], "count": 0,
                    "predicted_avg": None, "actual_rate": None,
                }
                continue
            predicted_avg = sum(p["probability"] for p in preds) / len(preds)
            actual_rate = sum(1 for p in preds if p.get("outcome")) / len(preds) * 100
            result["buckets"][name] = {
                "label": data["label"], "count": len(preds),
                "predicted_avg": round(predicted_avg, 1),
                "actual_rate": round(actual_rate, 1),
            }
        return result


calibration = CalibrationTracker()
