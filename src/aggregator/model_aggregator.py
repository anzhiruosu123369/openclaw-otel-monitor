"""Model usage aggregator."""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class ModelAggregator:
    """Aggregates model usage statistics."""

    def __init__(self):
        self._stats: Dict[str, Any] = {}
        self._call_history: List[Dict] = []
        self._max_history_size = 1000  # Limit history to prevent memory leak

    def update_from_sessions(self, sessions: Dict[str, Any]):
        """Update statistics from session model changes."""
        model_calls = defaultdict(lambda: {
            "calls": 0,
            "providers": defaultdict(int),
            "sessions": [],
        })

        for session_key, session in sessions.items():
            if hasattr(session, 'model_changes'):
                for change in session.model_changes:
                    model = change.get("model", "unknown")
                    provider = change.get("provider", "unknown")

                    model_calls[model]["calls"] += 1
                    model_calls[model]["providers"][provider] += 1
                    model_calls[model]["sessions"].append(session_key)

                    self._call_history.append({
                        "model": model,
                        "provider": provider,
                        "session_key": session_key,
                        "timestamp": change.get("timestamp"),
                    })

        # Limit history size to prevent memory leak
        if len(self._call_history) > self._max_history_size:
            self._call_history = self._call_history[-self._max_history_size:]

        # Calculate distribution
        total_calls = sum(m["calls"] for m in model_calls.values())

        self._stats = {
            "model_calls": dict(model_calls),
            "total_calls": total_calls,
            "unique_models": len(model_calls),
            "updated_at": datetime.now().isoformat(),
        }

    def update_from_db_stats(self, db_stats: List[Dict]):
        """Update from database statistics."""
        self._stats["db_stats"] = db_stats

        # Calculate totals
        total_input = sum(s.get("total_input_tokens", 0) for s in db_stats)
        total_output = sum(s.get("total_output_tokens", 0) for s in db_stats)
        total_calls = sum(s.get("total_calls", 0) for s in db_stats)

        self._stats["total_tokens"] = {
            "input": total_input,
            "output": total_output,
            "total": total_input + total_output,
        }

        # Model ranking
        ranked = sorted(db_stats, key=lambda s: s.get("total_calls", 0), reverse=True)
        self._stats["top_models"] = ranked[:5]

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return self._stats

    def get_model_distribution(self) -> Dict[str, int]:
        """Get call distribution by model."""
        return {
            model: data["calls"]
            for model, data in self._stats.get("model_calls", {}).items()
        }

    def get_token_summary(self) -> Dict[str, Any]:
        """Get token usage summary."""
        return self._stats.get("total_tokens", {
            "input": 0,
            "output": 0,
            "total": 0,
        })

    def get_recent_calls(self, limit: int = 20) -> List[Dict]:
        """Get recent model calls."""
        recent = sorted(
            self._call_history,
            key=lambda c: c.get("timestamp", ""),
            reverse=True
        )
        return recent[:limit]