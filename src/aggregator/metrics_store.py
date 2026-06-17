"""SQLite-based metrics storage."""

import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """A single metric data point."""
    name: str
    value: float
    timestamp: datetime
    labels: Dict[str, str]


class MetricsStore:
    """SQLite-based metrics storage with time-series support."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._pending_writes: List[tuple] = []
        self._batch_size = 50  # Batch writes for better performance
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp TEXT NOT NULL,
                labels TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name);
            CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp);

            CREATE TABLE IF NOT EXISTS sessions (
                session_key TEXT PRIMARY KEY,
                session_id TEXT,
                agent_id TEXT,
                status TEXT,
                last_user_message TEXT,
                last_assistant_message TEXT,
                last_model TEXT,
                last_provider TEXT,
                channel TEXT,
                message_count INTEGER DEFAULT 0,
                tool_calls TEXT,
                model_changes TEXT,
                updated_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);

            CREATE TABLE IF NOT EXISTS model_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                provider TEXT,
                call_count INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                total_latency_ms REAL DEFAULT 0,
                date TEXT,
                UNIQUE(model, provider, date)
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT,
                provider TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                timestamp TEXT,
                session_key TEXT,
                UNIQUE(session_key, timestamp, model, provider)
            );

            CREATE INDEX IF NOT EXISTS idx_token_timestamp ON token_usage(timestamp);
            CREATE INDEX IF NOT EXISTS idx_token_session ON token_usage(session_key);
        """)
        conn.commit()

    def record_metric(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a metric data point."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO metrics (name, value, timestamp, labels) VALUES (?, ?, ?, ?)",
            (name, value, datetime.now().isoformat(), json.dumps(labels or {}))
        )
        conn.commit()

    def get_metrics(self, name: str, since: datetime = None, limit: int = 100) -> List[MetricPoint]:
        """Get metric history."""
        conn = self._get_conn()
        query = "SELECT * FROM metrics WHERE name = ?"
        params = [name]

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        return [
            MetricPoint(
                name=row["name"],
                value=row["value"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                labels=json.loads(row["labels"]) if row["labels"] else {},
            )
            for row in rows
        ]

    def upsert_session(self, session_data: Dict[str, Any]):
        """Upsert session data."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO sessions (
                session_key, session_id, agent_id, status,
                last_user_message, last_assistant_message,
                last_model, last_provider, channel,
                message_count, tool_calls, model_changes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_data.get("session_key"),
            session_data.get("session_id"),
            session_data.get("agent_id"),
            session_data.get("status"),
            session_data.get("last_user_message"),
            session_data.get("last_assistant_message"),
            session_data.get("last_model"),
            session_data.get("last_provider"),
            session_data.get("channel"),
            session_data.get("message_count", 0),
            json.dumps(session_data.get("tool_calls", [])),
            json.dumps(session_data.get("model_changes", [])),
            session_data.get("updated_at", datetime.now()).isoformat() if isinstance(session_data.get("updated_at"), datetime) else session_data.get("updated_at"),
        ))
        conn.commit()

    def get_sessions(self, status: str = None, limit: int = 50) -> List[Dict]:
        """Get sessions from database."""
        conn = self._get_conn()
        query = "SELECT * FROM sessions"
        params = []

        if status:
            query += " WHERE status = ?"
            params.append(status)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]

    def record_model_call(self, model: str, provider: str, input_tokens: int = 0,
                          output_tokens: int = 0, latency_ms: float = 0, error: bool = False,
                          session_key: str = None, timestamp: str = None):
        """Record a model call with deduplication support.

        Uses token_usage table as the source of truth with unique constraint.
        model_stats is derived from token_usage to avoid double-counting.
        Uses batch writes for better performance.
        """
        conn = self._get_conn()

        # Record in token_usage with deduplication (INSERT OR IGNORE)
        # Use provided timestamp or current time
        ts = timestamp or datetime.now().isoformat()

        # Check if this record already exists (deduplication)
        if session_key:
            existing = conn.execute("""
                SELECT 1 FROM token_usage
                WHERE session_key = ? AND timestamp = ? AND model = ? AND provider = ?
            """, (session_key, ts, model, provider)).fetchone()

            if existing:
                # Already recorded, skip to avoid duplicate
                return

            # Add to pending batch
            self._pending_writes.append((model, provider, input_tokens, output_tokens, ts, session_key))
        else:
            # Fallback for calls without session_key (backward compatible, no dedup)
            self._pending_writes.append((model, provider, input_tokens, output_tokens, ts, None))

        # Flush batch when size threshold reached
        if len(self._pending_writes) >= self._batch_size:
            self._flush_pending_writes()

    def _flush_pending_writes(self):
        """Flush pending writes to database in batch."""
        if not self._pending_writes:
            return

        conn = self._get_conn()

        # Batch insert
        for model, provider, input_tokens, output_tokens, ts, session_key in self._pending_writes:
            if session_key:
                conn.execute("""
                    INSERT INTO token_usage (model, provider, input_tokens, output_tokens, timestamp, session_key)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (model, provider, input_tokens, output_tokens, ts, session_key))
            else:
                conn.execute("""
                    INSERT INTO token_usage (model, provider, input_tokens, output_tokens, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (model, provider, input_tokens, output_tokens, ts))

        conn.commit()
        self._pending_writes.clear()

    def get_model_stats(self, days: int = 7) -> List[Dict]:
        """Get model statistics from token_usage table (source of truth)."""
        conn = self._get_conn()
        since = (datetime.now() - timedelta(days=days)).isoformat()

        # Aggregate from token_usage to avoid double-counting
        rows = conn.execute("""
            SELECT
                model,
                provider,
                COUNT(*) as total_calls,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                0 as total_errors,
                0.0 as avg_latency_ms
            FROM token_usage
            WHERE timestamp >= ?
            GROUP BY model, provider
            ORDER BY total_calls DESC
        """, (since,)).fetchall()

        return [dict(row) for row in rows]

    def get_token_usage_timeseries(self, hours: int = 24) -> List[Dict]:
        """Get token usage over time."""
        conn = self._get_conn()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()

        rows = conn.execute("""
            SELECT
                strftime('%Y-%m-%d %H:00', timestamp) as hour,
                model,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens
            FROM token_usage
            WHERE timestamp >= ?
            GROUP BY hour, model
            ORDER BY hour
        """, (since,)).fetchall()

        return [dict(row) for row in rows]

    def get_token_usage_daily(self, days: int = 30) -> List[Dict]:
        """Get token usage aggregated by day."""
        conn = self._get_conn()
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        rows = conn.execute("""
            SELECT
                DATE(timestamp) as date,
                model,
                provider,
                COUNT(*) as calls,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens
            FROM token_usage
            WHERE DATE(timestamp) >= ?
            GROUP BY DATE(timestamp), model, provider
            ORDER BY date
        """, (since,)).fetchall()

        return [dict(row) for row in rows]

    def get_tpm_stats(self, hours: int = 24, agent_id: str = None) -> Dict[str, Any]:
        """Get TPM (Tokens Per Minute) statistics.
        
        Returns:
            - peak_tpm: Maximum TPM in the period
            - avg_tpm: Average TPM over the period
            - peak_time: Timestamp when peak occurred
            - current_tpm: TPM in the last minute
            - tpm_timeseries: TPM per minute for charting
        """
        conn = self._get_conn()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        # Query token usage aggregated by minute
        query = """
            SELECT
                strftime('%Y-%m-%d %H:%M', timestamp) as minute,
                SUM(input_tokens + output_tokens) as total_tokens,
                COUNT(*) as calls
            FROM token_usage
            WHERE timestamp >= ?
        """
        params = [since]
        
        # Filter by agent if specified (via session_key prefix)
        if agent_id:
            query += " AND session_key LIKE ?"
            params.append(f"%:{agent_id}:%")
        
        query += " GROUP BY minute ORDER BY minute"
        
        rows = conn.execute(query, params).fetchall()
        
        if not rows:
            return {
                "peak_tpm": 0,
                "avg_tpm": 0,
                "peak_time": None,
                "current_tpm": 0,
                "tpm_timeseries": [],
                "total_tokens": 0,
                "total_calls": 0,
            }
        
        # Calculate TPM for each minute
        tpm_data = []
        for row in rows:
            tpm_data.append({
                "minute": row["minute"],
                "tokens": row["total_tokens"] or 0,
                "calls": row["calls"],
                "tpm": row["total_tokens"] or 0,  # Already per minute
            })
        
        # Find peak TPM
        peak = max(tpm_data, key=lambda x: x["tpm"])
        
        # Calculate average TPM (total tokens / total minutes with data)
        total_tokens = sum(d["tokens"] for d in tpm_data)
        total_calls = sum(d["calls"] for d in tpm_data)
        active_minutes = len(tpm_data)
        avg_tpm = total_tokens / active_minutes if active_minutes > 0 else 0
        
        # Current TPM (last minute with data)
        current_tpm = tpm_data[-1]["tpm"] if tpm_data else 0
        
        return {
            "peak_tpm": peak["tpm"],
            "peak_time": peak["minute"],
            "avg_tpm": round(avg_tpm, 2),
            "current_tpm": current_tpm,
            "tpm_timeseries": tpm_data,
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "active_minutes": active_minutes,
        }

    def get_tpm_by_agent(self, hours: int = 24) -> List[Dict]:
        """Get TPM statistics grouped by agent."""
        conn = self._get_conn()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        # Extract agent_id from session_key pattern: "agent:{agent_id}:..."
        query = """
            SELECT
                CASE 
                    WHEN session_key LIKE 'agent:%' THEN 
                        SUBSTR(session_key, 7, INSTR(SUBSTR(session_key, 7), ':') - 1)
                    ELSE 'unknown'
                END as agent_id,
                strftime('%Y-%m-%d %H:%M', timestamp) as minute,
                SUM(input_tokens + output_tokens) as total_tokens,
                COUNT(*) as calls
            FROM token_usage
            WHERE timestamp >= ?
            GROUP BY agent_id, minute
            ORDER BY minute
        """
        
        rows = conn.execute(query, (since,)).fetchall()
        
        # Aggregate by agent
        agent_stats = {}
        for row in rows:
            agent = row["agent_id"] or "unknown"
            if agent not in agent_stats:
                agent_stats[agent] = {
                    "agent_id": agent,
                    "tpm_data": [],
                    "total_tokens": 0,
                    "total_calls": 0,
                }
            agent_stats[agent]["tpm_data"].append({
                "minute": row["minute"],
                "tpm": row["total_tokens"] or 0,
                "calls": row["calls"],
            })
            agent_stats[agent]["total_tokens"] += row["total_tokens"] or 0
            agent_stats[agent]["total_calls"] += row["calls"]
        
        # Calculate peak and avg for each agent
        result = []
        for agent_id, stats in agent_stats.items():
            tpm_values = [d["tpm"] for d in stats["tpm_data"]]
            result.append({
                "agent_id": agent_id,
                "peak_tpm": max(tpm_values) if tpm_values else 0,
                "avg_tpm": round(sum(tpm_values) / len(tpm_values), 2) if tpm_values else 0,
                "total_tokens": stats["total_tokens"],
                "total_calls": stats["total_calls"],
                "current_tpm": tpm_values[-1] if tpm_values else 0,
            })
        
        return sorted(result, key=lambda x: x["total_tokens"], reverse=True)

    def cleanup_old_data(self, days: int = 7):
        """Remove data older than retention period."""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM token_usage WHERE timestamp < ?", (cutoff,))

        date_cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM model_stats WHERE date < ?", (date_cutoff,))

        conn.commit()
        logger.info(f"Cleaned up data older than {days} days")

    def close(self):
        """Close database connection."""
        # Flush any pending writes before closing
        self._flush_pending_writes()

        if self._conn:
            self._conn.close()
            self._conn = None
