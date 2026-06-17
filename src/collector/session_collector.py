"""Session data collector from JSONL files."""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

logger = logging.getLogger(__name__)


@dataclass
class SessionEvent:
    """Represents a single event from a session transcript."""
    event_type: str
    timestamp: str
    session_id: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """Current state of a session."""
    session_key: str
    session_id: str
    agent_id: str
    status: str = "UNKNOWN"  # WORKING, FINISHED, INTERRUPTED, NO_MESSAGE
    last_user_message: Optional[str] = None
    last_assistant_message: Optional[str] = None
    last_model: Optional[str] = None
    last_provider: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    channel: Optional[str] = None
    message_count: int = 0
    tool_calls: List[str] = field(default_factory=list)
    model_changes: List[Dict[str, Any]] = field(default_factory=list)
    model_errors: List[Dict[str, Any]] = field(default_factory=list)  # 模型错误记录
    last_error: Optional[str] = None  # 最后一个错误消息
    total_input_tokens: int = 0  # 总输入 tokens
    total_output_tokens: int = 0  # 总输出 tokens
    token_usage: List[Dict[str, Any]] = field(default_factory=list)  # token 使用记录


class SessionCollector:
    """Collects session data from OpenClaw JSONL files."""

    def __init__(self, openclaw_root: Path):
        self.openclaw_root = openclaw_root
        self.sessions: Dict[str, SessionState] = {}
        self._observer: Optional[Observer] = None
        self._callbacks: List[callable] = []
        self._running = False
        # Event cache to avoid repeated JSONL parsing
        self._event_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_max_size = 100
        self._cache_max_age = 60  # seconds

    def add_callback(self, callback: callable):
        """Add a callback to be called when session data changes."""
        self._callbacks.append(callback)

    async def _notify_callbacks(self, event_type: str, data: Any):
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_type, data)
                else:
                    callback(event_type, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_agents_dir(self) -> Path:
        """Get the agents directory."""
        return self.openclaw_root / "agents"

    def get_all_agents(self) -> List[str]:
        """Get list of all agent IDs."""
        agents_dir = self.get_agents_dir()
        if not agents_dir.exists():
            return []
        return [d.name for d in agents_dir.iterdir() if d.is_dir()]

    def parse_sessions_json(self, agent_id: str) -> Dict[str, Any]:
        """Parse the sessions.json file for an agent."""
        sessions_file = self.get_agents_dir() / agent_id / "sessions" / "sessions.json"
        if not sessions_file.exists():
            return {}
        try:
            with open(sessions_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error parsing {sessions_file}: {e}")
            return {}

    def parse_jsonl_file(self, jsonl_path: Path) -> List[Dict[str, Any]]:
        """Parse a JSONL transcript file."""
        events = []
        try:
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error parsing {jsonl_path}: {e}")
        return events

    def extract_session_state(self, session_key: str, session_info: Dict, events: List[Dict]) -> SessionState:
        """Extract session state from sessions.json and events."""
        session_id = session_info.get("sessionId", "")
        agent_id = session_key.split(":")[1] if ":" in session_key else "unknown"

        state = SessionState(
            session_key=session_key,
            session_id=session_id,
            agent_id=agent_id,
            channel=session_info.get("lastChannel") or session_info.get("deliveryContext", {}).get("channel"),
        )

        # Parse update timestamp - 从 session_info 直接获取
        updated_at_ts = session_info.get("updatedAt")
        if updated_at_ts:
            try:
                state.updated_at = datetime.fromtimestamp(updated_at_ts / 1000)
            except Exception as e:
                logger.warning(f"Failed to parse updatedAt for {session_key}: {e}")

        # Process events
        last_user_msg = None
        last_assistant_msg = None

        for event in events:
            event_type = event.get("type", "")

            if event_type == "message":
                msg = event.get("message", {})
                role = msg.get("role", "")
                content = msg.get("content", "")

                # 检查模型错误 (stopReason: "error")
                stop_reason = msg.get("stopReason", "")
                if stop_reason == "error":
                    error_msg = msg.get("errorMessage", "Unknown error")
                    model = msg.get("model", state.last_model or "unknown")
                    provider = msg.get("provider", state.last_provider or "unknown")
                    state.model_errors.append({
                        "model": model,
                        "provider": provider,
                        "error": error_msg,
                        "timestamp": event.get("timestamp"),
                    })
                    state.last_error = error_msg

                # Extract text from content
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            texts.append(item)
                    content = " ".join(texts)
                elif not isinstance(content, str):
                    content = str(content)

                if role == "user":
                    last_user_msg = content[:200] if content else None
                    state.message_count += 1
                elif role == "assistant":
                    last_assistant_msg = content[:200] if content else None

                    # 解析 token 使用
                    usage = msg.get("usage", {})
                    if usage:
                        input_tokens = usage.get("input", 0) or usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("output", 0) or usage.get("completion_tokens", 0)
                        state.total_input_tokens += input_tokens
                        state.total_output_tokens += output_tokens
                        if input_tokens > 0 or output_tokens > 0:
                            state.token_usage.append({
                                "model": msg.get("model", state.last_model or "unknown"),
                                "provider": msg.get("provider", state.last_provider or "unknown"),
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "timestamp": event.get("timestamp"),
                            })

            elif event_type == "model_change":
                state.last_model = event.get("modelId")
                state.last_provider = event.get("provider")
                state.model_changes.append({
                    "model": event.get("modelId"),
                    "provider": event.get("provider"),
                    "timestamp": event.get("timestamp"),
                })

            elif event_type == "tool":
                tool_name = event.get("toolName") or event.get("name", "unknown")
                state.tool_calls.append(tool_name)

            elif event_type == "custom":
                custom_type = event.get("customType", "")
                # 处理 prompt-error 事件
                if custom_type == "openclaw:prompt-error":
                    data = event.get("data", {})
                    state.model_errors.append({
                        "model": data.get("model", "unknown"),
                        "provider": data.get("provider", "unknown"),
                        "error": data.get("error", "Unknown error"),
                        "timestamp": event.get("timestamp"),
                    })
                    state.last_error = data.get("error", "Unknown error")

        state.last_user_message = last_user_msg
        state.last_assistant_message = last_assistant_msg

        # Determine status based on last event
        if events:
            last_event = events[-1]
            last_type = last_event.get("type", "")
            if last_type == "lifecycle":
                phase = last_event.get("phase", "")
                if phase == "start":
                    state.status = "WORKING"
                elif phase == "end":
                    state.status = "FINISHED"
                elif phase == "error":
                    state.status = "INTERRUPTED"
            elif last_type == "message":
                # Recent message indicates working or finished
                if state.updated_at:
                    age = (datetime.now() - state.updated_at).total_seconds()
                    if age < 60:  # Less than 1 minute ago
                        state.status = "WORKING"
                    else:
                        state.status = "FINISHED"
        else:
            state.status = "NO_MESSAGE"

        return state

    async def scan_all_sessions(self):
        """Scan all sessions for all agents."""
        agents = self.get_all_agents()
        for agent_id in agents:
            await self.scan_agent_sessions(agent_id)

    async def scan_agent_sessions(self, agent_id: str):
        """Scan all sessions for a specific agent."""
        sessions_data = self.parse_sessions_json(agent_id)
        sessions_dir = self.get_agents_dir() / agent_id / "sessions"

        for session_key, session_info in sessions_data.items():
            session_file = session_info.get("sessionFile", "")
            if not session_file:
                # Try to find JSONL file by session ID
                session_id = session_info.get("sessionId", "")
                if session_id:
                    possible_file = sessions_dir / f"{session_id}.jsonl"
                    if possible_file.exists():
                        session_file = str(possible_file)

            if session_file:
                jsonl_path = Path(session_file).expanduser()
                if jsonl_path.exists():
                    events = self.parse_jsonl_file(jsonl_path)
                    state = self.extract_session_state(session_key, session_info, events)
                    self.sessions[session_key] = state
                    await self._notify_callbacks("session_update", state)

    def get_active_sessions(self) -> List[SessionState]:
        """Get all currently active sessions."""
        return [s for s in self.sessions.values() if s.status in ("WORKING", "NO_MESSAGE")]

    def get_recent_sessions(self, limit: int = 20) -> List[SessionState]:
        """Get most recently updated sessions."""
        sorted_sessions = sorted(
            self.sessions.values(),
            key=lambda s: s.updated_at or datetime.min,
            reverse=True
        )
        return sorted_sessions[:limit]

    def get_events_cached(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Get cached events for a session to avoid repeated JSONL parsing."""
        import time

        # Check cache
        if session_key in self._event_cache:
            cached = self._event_cache[session_key]
            if time.time() - cached['timestamp'] < self._cache_max_age:
                return cached['data']

        # Load and cache events
        if session_key not in self.sessions:
            return None

        state = self.sessions[session_key]
        jsonl_path = None

        # Find JSONL file
        sessions_dir = self.get_agents_dir() / state.agent_id / "sessions"
        if state.session_id:
            possible_file = sessions_dir / f"{state.session_id}.jsonl"
            if possible_file.exists():
                jsonl_path = possible_file

        if not jsonl_path or not jsonl_path.exists():
            return None

        # Parse all events (only when cache miss)
        all_events = []
        try:
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        all_events.append(event)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error loading cached events: {e}")
            return None

        # Store in cache
        cached_data = {
            'events': all_events,
            'total': len(all_events),
        }

        # Cleanup old cache entries if too large
        if len(self._event_cache) >= self._cache_max_size:
            # Remove oldest entries
            oldest_keys = sorted(
                self._event_cache.keys(),
                key=lambda k: self._event_cache[k]['timestamp']
            )[:len(self._event_cache) - self._cache_max_size + 1]
            for k in oldest_keys:
                del self._event_cache[k]

        self._event_cache[session_key] = {
            'data': cached_data,
            'timestamp': time.time(),
        }

        return cached_data

    def start_watching(self):
        """Start watching for file changes."""
        if self._observer:
            return

        class Handler(FileSystemEventHandler):
            def __init__(self, collector):
                self.collector = collector

            def on_modified(self, event):
                if event.src_path.endswith(('.jsonl', '.json')):
                    asyncio.create_task(self.collector._handle_file_change(event.src_path))

            def on_created(self, event):
                if event.src_path.endswith(('.jsonl', '.json')):
                    asyncio.create_task(self.collector._handle_file_change(event.src_path))

        self._observer = Observer()
        handler = Handler(self)
        self._observer.schedule(handler, str(self.get_agents_dir()), recursive=True)
        self._observer.start()
        self._running = True
        logger.info(f"Started watching {self.get_agents_dir()}")

    async def _handle_file_change(self, path: str):
        """Handle a file change event."""
        path = Path(path)
        # Extract agent_id from path
        parts = path.parts
        if "agents" in parts:
            idx = parts.index("agents")
            if len(parts) > idx + 1:
                agent_id = parts[idx + 1]
                await self.scan_agent_sessions(agent_id)

    def stop_watching(self):
        """Stop watching for file changes."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        self._running = False

    async def get_tpm_stats(self, hours: int = 24, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculate Tokens Per Minute statistics.
        
        Args:
            hours: Number of hours to analyze (default 24)
            agent_id: Optional agent filter
            
        Returns:
            Dict with peak_tpm, avg_tpm, current_tpm, active_minutes, peak_time, tpm_timeseries
        """
        from datetime import timedelta
        
        now = datetime.now()
        start_time = now - timedelta(hours=hours)
        
        # Collect all token usage events with timestamps
        token_events = []  # (timestamp, input_tokens, output_tokens, agent_id)
        
        for session in self.sessions.values():
            # Filter by agent if specified
            if agent_id and session.agent_id != agent_id:
                continue
            
            # Get cached events for this session
            cached = self.get_events_cached(session.session_key)
            if not cached or 'events' not in cached:
                continue
            
            events = cached['events']
            for event in events:
                event_type = event.get('type', '')
                if event_type == 'message':
                    timestamp_str = event.get('timestamp', '')
                    if not timestamp_str:
                        continue
                    
                    # Parse timestamp
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        if timestamp.tzinfo:
                            timestamp = timestamp.astimezone().replace(tzinfo=None)
                    except:
                        continue
                    
                    # Filter by time range
                    if timestamp < start_time:
                        continue
                    
                    # Token data is in message.usage field
                    message = event.get('message', {})
                    usage = message.get('usage', {})
                    
                    # Try multiple possible field names for tokens
                    input_tokens = (
                        usage.get('input', 0) or 
                        usage.get('inputTokens', 0) or 
                        message.get('inputTokens', 0) or 
                        0
                    )
                    output_tokens = (
                        usage.get('output', 0) or 
                        usage.get('outputTokens', 0) or 
                        message.get('outputTokens', 0) or 
                        0
                    )
                    total_tokens = input_tokens + output_tokens
                    
                    if total_tokens > 0:
                        token_events.append({
                            'timestamp': timestamp,
                            'tokens': total_tokens,
                            'agent_id': session.agent_id,
                        })
        
        if not token_events:
            return {
                'peak_tpm': 0,
                'avg_tpm': 0,
                'current_tpm': 0,
                'active_minutes': 0,
                'peak_time': None,
                'tpm_timeseries': [],
            }
        
        # Sort by timestamp
        token_events.sort(key=lambda x: x['timestamp'])
        
        # Calculate TPM per minute bucket
        minute_buckets = {}  # minute_str -> total_tokens
        
        for event in token_events:
            # Round down to minute
            minute_key = event['timestamp'].strftime('%Y-%m-%d %H:%M')
            if minute_key not in minute_buckets:
                minute_buckets[minute_key] = 0
            minute_buckets[minute_key] += event['tokens']
        
        # Build time series
        tpm_timeseries = []
        for minute_str, tokens in sorted(minute_buckets.items()):
            tpm_timeseries.append({
                'minute': minute_str,
                'tpm': tokens,  # Tokens in this minute = TPM for this minute
            })
        
        # Calculate statistics
        if tpm_timeseries:
            tpm_values = [d['tpm'] for d in tpm_timeseries]
            peak_tpm = max(tpm_values)
            avg_tpm = sum(tpm_values) / len(tpm_values)
            
            # Find peak time
            peak_idx = tpm_values.index(peak_tpm)
            peak_time = tpm_timeseries[peak_idx]['minute']
            
            # Current TPM (last minute with activity)
            current_tpm = tpm_values[-1] if tpm_values else 0
            
            active_minutes = len(tpm_timeseries)
        else:
            peak_tpm = 0
            avg_tpm = 0
            current_tpm = 0
            peak_time = None
            active_minutes = 0
        
        return {
            'peak_tpm': peak_tpm,
            'avg_tpm': round(avg_tpm, 1),
            'current_tpm': current_tpm,
            'active_minutes': active_minutes,
            'peak_time': peak_time,
            'tpm_timeseries': tpm_timeseries,
        }
