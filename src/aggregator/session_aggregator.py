"""Session aggregator for statistics."""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from collections import defaultdict
import logging

from ..collector.session_collector import SessionState

logger = logging.getLogger(__name__)


class SessionAggregator:
    """Aggregates session statistics."""

    def __init__(self):
        self._stats: Dict[str, Any] = {}

    def update_from_sessions(self, sessions: Dict[str, SessionState]):
        """Update statistics from session data."""
        status_counts = defaultdict(int)
        agent_counts = defaultdict(int)
        channel_counts = defaultdict(int)
        recent_sessions = []

        now = datetime.now()

        for session in sessions.values():
            status_counts[session.status] += 1
            agent_counts[session.agent_id] += 1
            if session.channel:
                channel_counts[session.channel] += 1

            # Track recent sessions (last hour)
            if session.updated_at:
                age = (now - session.updated_at).total_seconds()
                if age < 3600:
                    recent_sessions.append({
                        "session_key": session.session_key,
                        "agent_id": session.agent_id,
                        "status": session.status,
                        "age_seconds": age,
                        "channel": session.channel,
                        "last_model": session.last_model,
                    })

        self._stats = {
            "total_sessions": len(sessions),
            "active_sessions": status_counts.get("WORKING", 0),
            "status_distribution": dict(status_counts),
            "agent_distribution": dict(agent_counts),
            "channel_distribution": dict(channel_counts),
            "recent_sessions": recent_sessions,
            "updated_at": now.isoformat(),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return self._stats

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary for dashboard."""
        return {
            "total": self._stats.get("total_sessions", 0),
            "active": self._stats.get("active_sessions", 0),
            "by_status": self._stats.get("status_distribution", {}),
            "by_agent": self._stats.get("agent_distribution", {}),
            "by_channel": self._stats.get("channel_distribution", {}),
        }