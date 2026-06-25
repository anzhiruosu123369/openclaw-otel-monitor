"""FastAPI REST endpoints."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import logging
import json

from ..cost import compute_cost, compute_costs

logger = logging.getLogger(__name__)

router = APIRouter()


# Global state (will be injected by app)
_store = None
_session_collector = None
_gateway_collector = None
_session_aggregator = None
_model_aggregator = None


def set_dependencies(store, session_collector, gateway_collector, session_aggregator, model_aggregator):
    """Set dependencies from main app."""
    global _store, _session_collector, _gateway_collector, _session_aggregator, _model_aggregator
    _store = store
    _session_collector = session_collector
    _gateway_collector = gateway_collector
    _session_aggregator = session_aggregator
    _model_aggregator = model_aggregator


@router.get("/health")
async def api_health():
    """Service health check."""
    return {
        "ok": True,
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/gateway/status")
async def api_gateway_status():
    """Gateway health status."""
    if _gateway_collector:
        status = _gateway_collector.status
        return {
            "healthy": status.healthy,
            "status": status.status,
            "last_check": status.last_check.isoformat() if status.last_check else None,
            "response_time_ms": status.response_time_ms,
            "error": status.error,
        }
    return {"healthy": False, "status": "unknown"}


@router.get("/gateway/metrics")
async def api_gateway_metrics():
    """Gateway metrics."""
    if _gateway_collector:
        metrics = _gateway_collector.metrics
        return {
            "connections": metrics.connections,
            "agents_running": metrics.agents_running,
            "messages_total": metrics.messages_total,
            "tokens_total": metrics.tokens_total,
        }
    return {}


@router.get("/sessions")
async def api_sessions(status: Optional[str] = None, limit: int = 50):
    """Get session list."""
    sessions = []

    # From live collector
    if _session_collector:
        for session_key, state in _session_collector.sessions.items():
            if status and state.status != status:
                continue

            # Parse timestamp to get date
            updated_at = state.updated_at
            date_str = None
            time_str = None
            if updated_at:
                try:
                    date_str = updated_at.strftime("%Y-%m-%d")
                    time_str = updated_at.strftime("%H:%M:%S")
                except:
                    pass

            sessions.append({
                "session_key": session_key,
                "session_id": state.session_id,
                "agent_id": state.agent_id,
                "status": state.status,
                "channel": state.channel,
                "last_model": state.last_model,
                "last_provider": state.last_provider,
                "last_user_message": state.last_user_message,
                "last_assistant_message": state.last_assistant_message,
                "message_count": state.message_count,
                "total_tokens": state.total_input_tokens + state.total_output_tokens,
                "total_cost": round(compute_cost(
                    state.last_model or "unknown",
                    state.last_provider or "",
                    state.total_input_tokens,
                    state.total_output_tokens,
                ), 4),
                "updated_at": updated_at.isoformat() if updated_at else None,
                "date": date_str,
                "time": time_str,
            })

    # Sort by updated_at
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)

    return sessions[:limit]


@router.get("/sessions/active")
async def api_sessions_active():
    """Get active sessions."""
    if _session_collector:
        active = _session_collector.get_active_sessions()
        return [
            {
                "session_key": s.session_key,
                "agent_id": s.agent_id,
                "status": s.status,
                "channel": s.channel,
                "last_model": s.last_model,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in active
        ]
    return []


@router.get("/sessions/{session_key}/trace")
async def api_session_trace(session_key: str, offset: int = 0, limit: int = 50):
    """Get trace events for a session with pagination support."""
    if _session_collector and session_key in _session_collector.sessions:
        state = _session_collector.sessions[session_key]

        # Use cached events if available
        events = []
        total_events = 0

        # Try to get cached events
        if hasattr(_session_collector, 'get_events_cached'):
            cached_result = _session_collector.get_events_cached(session_key)
            if cached_result:
                all_events = cached_result['events']
                total_events = cached_result['total']
                # Process events for display and apply pagination
                processed_events = [process_event_for_display(e) for e in all_events]
                events = processed_events[offset:offset + limit]
        else:
            # Fallback: stream parse with early termination
            jsonl_path = None

            # Find the JSONL file
            if _session_collector:
                import json
                from pathlib import Path

                agent_id = state.agent_id
                sessions_dir = _session_collector.get_agents_dir() / agent_id / "sessions"

                # Try to find by session_id
                if state.session_id:
                    possible_file = sessions_dir / f"{state.session_id}.jsonl"
                    if possible_file.exists():
                        jsonl_path = possible_file

                # Stream parse with early termination
                if jsonl_path and jsonl_path.exists():
                    try:
                        all_events = []
                        line_count = 0
                        with open(jsonl_path, "r") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                line_count += 1

                                # Early termination: stop if we have enough
                                if line_count > offset + limit + 100:
                                    break

                                try:
                                    event = json.loads(line)
                                    processed_event = process_event_for_display(event)
                                    all_events.append(processed_event)
                                except json.JSONDecodeError:
                                    continue

                        total_events = line_count  # Approximate
                        events = all_events[offset:offset + limit]
                    except Exception as e:
                        logger.error(f"Error parsing JSONL for trace: {e}")

        return {
            "session_key": session_key,
            "agent_id": state.agent_id,
            "status": state.status,
            "events": events,
            "event_count": total_events,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total_events,
        }
    return {"error": "Session not found", "events": [], "has_more": False}


def process_event_for_display(event: Dict) -> Dict:
    """Process an event for display in trace view."""
    event_type = event.get("type", "")

    result = {
        "type": event_type,
        "timestamp": event.get("timestamp"),
        "id": event.get("id"),
        "parent_id": event.get("parentId"),
    }

    if event_type == "message":
        msg = event.get("message", {})
        role = msg.get("role", "")

        # Extract content
        content = msg.get("content", "")
        tool_calls = []
        tool_results = []

        # Handle toolResult role - tool result info is at message level
        if role == "toolResult":
            # Extract tool result from message-level fields
            tool_results.append({
                "tool_use_id": msg.get("toolCallId", ""),
                "tool_name": msg.get("toolName", ""),
                "content": content if isinstance(content, str) else 
                           "\n".join([item.get("text", "") for item in content 
                                     if isinstance(item, dict) and item.get("type") == "text"]),
                "is_error": msg.get("isError", False)
            })
        elif isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "")
                    if item_type == "text":
                        texts.append(item.get("text", ""))
                    elif item_type in ("tool_use", "toolCall"):
                        # Extract tool call info (support both formats)
                        tool_calls.append({
                            "id": item.get("id"),
                            "name": item.get("name", "unknown"),
                            "input": item.get("input") or item.get("arguments", {})
                        })
                    elif item_type in ("tool_result", "toolResult"):
                        # Extract tool result info (support both formats)
                        tool_results.append({
                            "tool_use_id": item.get("tool_use_id") or item.get("toolCallId", ""),
                            "content": item.get("content", ""),
                            "status": item.get("status", "success")
                        })
                elif isinstance(item, str):
                    texts.append(item)
            content = "\n".join(texts)

        result["role"] = role
        result["content"] = content[:500] if content else ""
        result["content_full"] = content
        result["model"] = msg.get("model")
        result["provider"] = msg.get("provider")
        result["stop_reason"] = msg.get("stopReason")
        result["tool_calls"] = tool_calls
        result["tool_results"] = tool_results
        
        # Handle toolResult role - extract from message top-level fields
        if role == "toolResult":
            result["tool_results"] = [{
                "tool_use_id": msg.get("toolCallId", ""),
                "tool_name": msg.get("toolName", ""),
                "content": content,
                "status": "error" if msg.get("isError") else "success"
            }]

        # Token usage
        usage = msg.get("usage", {})
        if usage:
            result["input_tokens"] = usage.get("input") or usage.get("prompt_tokens", 0)
            result["output_tokens"] = usage.get("output") or usage.get("completion_tokens", 0)

        # Error info
        if msg.get("stopReason") == "error":
            result["error"] = msg.get("errorMessage")

    elif event_type == "tool":
        result["tool_name"] = event.get("toolName") or event.get("name")
        result["tool_input"] = str(event.get("input", ""))[:500]
        result["tool_result"] = str(event.get("result", ""))[:1000]
        result["status"] = event.get("status")

    elif event_type == "model_change":
        result["model"] = event.get("modelId")
        result["provider"] = event.get("provider")

    elif event_type == "lifecycle":
        result["phase"] = event.get("phase")
        result["reason"] = event.get("reason")

    elif event_type == "thinking_level_change":
        result["thinking_level"] = event.get("thinkingLevel")

    elif event_type == "custom":
        result["custom_type"] = event.get("customType")
        result["data"] = event.get("data")

    elif event_type == "session":
        result["version"] = event.get("version")
        result["cwd"] = event.get("cwd")

    return result


@router.get("/sessions/{session_key}")
async def api_session_detail(session_key: str):
    """Get session details with full trace info."""
    if _session_collector and session_key in _session_collector.sessions:
        state = _session_collector.sessions[session_key]

        # Get token usage summary
        token_summary = {
            "total_input": state.total_input_tokens,
            "total_output": state.total_output_tokens,
            "by_model": {},
        }
        for usage in state.token_usage:
            model = usage.get("model", "unknown")
            if model not in token_summary["by_model"]:
                token_summary["by_model"][model] = {"input": 0, "output": 0}
            token_summary["by_model"][model]["input"] += usage.get("input_tokens", 0)
            token_summary["by_model"][model]["output"] += usage.get("output_tokens", 0)

        return {
            "session_key": session_key,
            "session_id": state.session_id,
            "agent_id": state.agent_id,
            "status": state.status,
            "channel": state.channel,
            "last_model": state.last_model,
            "last_provider": state.last_provider,
            "last_user_message": state.last_user_message,
            "last_assistant_message": state.last_assistant_message,
            "message_count": state.message_count,
            "tool_calls": state.tool_calls,
            "model_changes": state.model_changes,
            "model_errors": state.model_errors,
            "last_error": state.last_error,
            "error_count": len(state.model_errors),
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            "created_at": state.created_at.isoformat() if state.created_at else None,
            # Token usage details
            "token_usage": state.token_usage,
            "token_summary": token_summary,
            "total_input_tokens": state.total_input_tokens,
            "total_output_tokens": state.total_output_tokens,
            "total_cost": round(sum(
                compute_cost(u.get("model", "unknown"), u.get("provider", ""),
                             u.get("input_tokens", 0), u.get("output_tokens", 0))
                for u in state.token_usage
            ), 4),
        }
    return {"error": "Session not found"}


@router.get("/errors")
async def api_errors(limit: int = 50, group_by: str = "agent", date: str = None,
                     start_date: str = None, end_date: str = None):
    """Get recent model errors across all sessions.

    Args:
        limit: Maximum number of errors to return
        group_by: Grouping mode - 'agent' returns grouped by agent, 'flat' returns flat list
        date: Filter by specific date (YYYY-MM-DD format)
        start_date: Filter errors from this date onwards (inclusive)
        end_date: Filter errors up to this date (inclusive)
    """
    errors = []

    if _session_collector:
        for session_key, state in _session_collector.sessions.items():
            for err in state.model_errors:
                # Parse timestamp to get date
                ts = err.get("timestamp")
                date_str = None
                time_str = None
                if ts:
                    try:
                        from datetime import datetime as dt
                        if isinstance(ts, (int, float)):
                            parsed = dt.fromtimestamp(ts / 1000)
                        else:
                            parsed = dt.fromisoformat(ts.replace("Z", "+00:00"))
                        date_str = parsed.strftime("%Y-%m-%d")
                        time_str = parsed.strftime("%H:%M:%S")
                    except:
                        pass

                # Apply date filters
                if date and date_str != date:
                    continue
                if start_date and date_str and date_str < start_date:
                    continue
                if end_date and date_str and date_str > end_date:
                    continue

                errors.append({
                    "session_key": session_key,
                    "agent_id": state.agent_id,
                    "model": err.get("model"),
                    "provider": err.get("provider"),
                    "error": err.get("error"),
                    "timestamp": err.get("timestamp"),
                    "date": date_str,
                    "time": time_str,
                })

    # Sort by timestamp
    errors.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    if group_by == "agent":
        # Group by agent_id
        grouped = {}
        for err in errors[:limit * 2]:  # Get more for grouping
            agent_id = err.get("agent_id", "unknown")
            if agent_id not in grouped:
                grouped[agent_id] = {
                    "agent_id": agent_id,
                    "error_count": 0,
                    "errors": [],
                }
            if len(grouped[agent_id]["errors"]) < limit:
                grouped[agent_id]["errors"].append(err)
            grouped[agent_id]["error_count"] += 1

        return {
            "grouped": list(grouped.values()),
            "flat": errors[:limit],
            "total": len(errors),
        }

    return errors[:limit]


@router.get("/errors/summary")
async def api_errors_summary():
    """Get error summary by model and provider."""
    error_counts = {}

    if _session_collector:
        for session_key, state in _session_collector.sessions.items():
            for err in state.model_errors:
                key = f"{err.get('provider', 'unknown')}:{err.get('model', 'unknown')}"
                if key not in error_counts:
                    error_counts[key] = {
                        "provider": err.get("provider", "unknown"),
                        "model": err.get("model", "unknown"),
                        "count": 0,
                        "recent_errors": [],
                    }
                error_counts[key]["count"] += 1
                if len(error_counts[key]["recent_errors"]) < 3:
                    error_counts[key]["recent_errors"].append(err.get("error", ""))

    return {
        "total_errors": sum(e["count"] for e in error_counts.values()),
        "by_model": list(error_counts.values()),
    }


@router.get("/models")
async def api_models():
    """Get model statistics."""
    stats = {}

    if _model_aggregator:
        stats["distribution"] = _model_aggregator.get_model_distribution()
        stats["tokens"] = _model_aggregator.get_token_summary()
        stats["recent_calls"] = _model_aggregator.get_recent_calls()
        stats["full"] = _model_aggregator.get_stats()

    if _store:
        stats["db"] = _store.get_model_stats()

    return stats


@router.get("/models/stats")
async def api_model_stats(days: int = 7):
    """Get detailed model statistics from database."""
    if _store:
        stats = _store.get_model_stats(days=days)
        # Add cost to each model
        for m in stats:
            m["total_cost"] = round(compute_cost(
                m.get("model", "unknown"),
                m.get("provider", ""),
                m.get("total_input_tokens", 0),
                m.get("total_output_tokens", 0),
            ), 4)
        return stats
    return []


@router.get("/tokens")
async def api_tokens():
    """Get token usage statistics."""
    result = {}

    if _model_aggregator:
        result["summary"] = _model_aggregator.get_token_summary()

    if _store:
        result["timeseries"] = _store.get_token_usage_timeseries(hours=24)

    return result


@router.get("/tokens/histogram")
async def api_tokens_histogram(hours: int = 24):
    """Get token usage histogram."""
    if _store:
        return _store.get_token_usage_timeseries(hours=hours)
    return []


@router.get("/tokens/daily")
async def api_tokens_daily(days: int = 30):
    """Get token usage aggregated by day or hour.
    
    Args:
        days: Time range in days. Special case: days=1 returns hourly data for last 24h.
    
    Returns:
        For days=1: hourly aggregated data (last 24 hours)
        For days>1: daily aggregated data
    """
    if _store:
        if days == 1:
            # Return hourly data for last 24 hours
            return _store.get_token_usage_timeseries(hours=24)
        else:
            return _store.get_token_usage_daily(days=days)
    return []


@router.get("/tpm")
async def api_tpm(hours: int = 24, agent_id: str = None):
    """Get TPM (Tokens Per Minute) statistics.
    
    Args:
        hours: Time range in hours (default 24)
        agent_id: Filter by specific agent (optional)
    
    Returns:
        peak_tpm: Maximum TPM in the period
        avg_tpm: Average TPM over active minutes
        current_tpm: TPM in the last minute
        tpm_timeseries: Per-minute data for charting
    """
    if _session_collector:
        tpm = await _session_collector.get_tpm_stats(hours=hours, agent_id=agent_id)
        return tpm
    return {
        "peak_tpm": 0,
        "avg_tpm": 0,
        "peak_time": None,
        "current_tpm": 0,
        "tpm_timeseries": [],
    }


@router.get("/tpm/by-agent")
async def api_tpm_by_agent(hours: int = 24):
    """Get TPM statistics grouped by agent.
    
    Returns peak_tpm, avg_tpm, current_tpm for each agent.
    """
    if _store:
        return _store.get_tpm_by_agent(hours=hours)
    return []


@router.get("/tools")
async def api_tools():
    """Get tool call statistics."""
    tool_calls = {}

    if _session_collector:
        for session in _session_collector.sessions.values():
            for tool in session.tool_calls:
                tool_calls[tool] = tool_calls.get(tool, 0) + 1

    return {
        "distribution": tool_calls,
        "total": sum(tool_calls.values()),
    }


@router.get("/dashboard")
async def api_dashboard():
    """Get dashboard aggregated data."""
    dashboard = {
        "timestamp": datetime.now().isoformat(),
        "gateway": {},
        "sessions": {},
        "models": {},
        "tokens": {},
    }

    if _gateway_collector:
        dashboard["gateway"] = {
            "healthy": _gateway_collector.status.healthy,
            "status": _gateway_collector.status.status,
            "response_time_ms": _gateway_collector.status.response_time_ms,
        }

    if _session_aggregator:
        dashboard["sessions"] = _session_aggregator.get_summary()

    if _model_aggregator:
        dashboard["models"] = {
            "distribution": _model_aggregator.get_model_distribution(),
            "top_models": _model_aggregator.get_stats().get("top_models", []),
        }
        dashboard["tokens"] = _model_aggregator.get_token_summary()

        # Cost summary from model stats
        model_stats = _model_aggregator.get_stats().get("db_stats", [])
        if model_stats:
            cost_summary = {"total_cost": 0.0, "by_model": []}
            for m in model_stats:
                cost = compute_cost(
                    m.get("model", "unknown"),
                    m.get("provider", ""),
                    m.get("total_input_tokens", 0),
                    m.get("total_output_tokens", 0),
                )
                cost_summary["total_cost"] += cost
                cost_summary["by_model"].append({
                    "model": m.get("model"),
                    "provider": m.get("provider"),
                    "cost": round(cost, 4),
                })
            cost_summary["total_cost"] = round(cost_summary["total_cost"], 4)
            dashboard["cost"] = cost_summary

    return dashboard


# WebSocket for real-time updates
class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)

    try:
        # Send initial data
        initial_data = await api_dashboard()
        await websocket.send_json({"type": "initial", "data": initial_data})

        while True:
            # Wait for client messages or just keep connection alive
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                # Handle subscription requests
                msg = json.loads(data)
                if msg.get("type") == "subscribe":
                    await websocket.send_json({"type": "subscribed", "channels": msg.get("channels", [])})
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat", "timestamp": datetime.now().isoformat()})

    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_update(event_type: str, data: Any):
    """Broadcast an update to all connected clients."""
    await manager.broadcast({"type": event_type, "data": data})