#!/usr/bin/env python3
"""Generate demo session data with parent-child event hierarchy for testing."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

openclaw_root = Path.home() / ".openclaw"
agent_id = "demo-agent"
session_key = "x:demo-agent"
session_id = "demo-001"
agents_dir = openclaw_root / "agents" / agent_id / "sessions"
agents_dir.mkdir(parents=True, exist_ok=True)

now = datetime.now()

# sessions.json - expected format: dict of session_key -> session_info
sessions_meta = {
    session_key: {
        "sessionId": session_id,
        "agentId": agent_id,
        "status": "FINISHED",
        "lastChannel": "web",
        "updatedAt": int(now.timestamp() * 1000),
        "createdAt": int((now - timedelta(minutes=30)).timestamp() * 1000),
    }
}

with open(agents_dir / "sessions.json", "w") as f:
    json.dump(sessions_meta, f, indent=2)

# Build demo JSONL events with parent-child hierarchy
events = [
    {
        "type": "session",
        "id": "sess-1",
        "parentId": None,
        "timestamp": (now - timedelta(minutes=30)).isoformat(),
        "version": "0.1.0",
        "cwd": "/home/demo"
    },
    {
        "type": "message",
        "id": "msg-1",
        "parentId": "sess-1",
        "timestamp": (now - timedelta(minutes=29)).isoformat(),
        "message": {
            "role": "user",
            "content": "帮我分析一下最近的销售数据",
            "model": None,
        }
    },
    {
        "type": "lifecycle",
        "id": "life-1",
        "parentId": "msg-1",
        "timestamp": (now - timedelta(minutes=28, seconds=50)).isoformat(),
        "phase": "start",
    },
    {
        "type": "model_change",
        "id": "mc-1",
        "parentId": "life-1",
        "timestamp": (now - timedelta(minutes=28, seconds=45)).isoformat(),
        "modelId": "deepseek-v4-pro",
        "provider": "deepseek",
    },
    {
        "type": "tool",
        "id": "tool-1",
        "parentId": "life-1",
        "timestamp": (now - timedelta(minutes=28, seconds=40)).isoformat(),
        "toolName": "search_sales_data",
        "input": {"query": "2024 Q4", "region": "all"},
        "status": "success",
    },
    {
        "type": "tool",
        "id": "tool-1-result",
        "parentId": "tool-1",
        "timestamp": (now - timedelta(minutes=28, seconds=20)).isoformat(),
        "toolName": "search_sales_data",
        "status": "success",
        "result": "Found 1,234 records with total revenue $5.6M",
    },
    {
        "type": "tool",
        "id": "tool-2",
        "parentId": "life-1",
        "timestamp": (now - timedelta(minutes=27, seconds=50)).isoformat(),
        "toolName": "analyze_trends",
        "input": {"data_points": 1234, "metric": "revenue"},
        "status": "success",
    },
    {
        "type": "model_change",
        "id": "mc-2",
        "parentId": "tool-2",
        "timestamp": (now - timedelta(minutes=27, seconds=45)).isoformat(),
        "modelId": "deepseek-v4-flash",
        "provider": "deepseek",
    },
    {
        "type": "tool",
        "id": "tool-2-result",
        "parentId": "tool-2",
        "timestamp": (now - timedelta(minutes=27, seconds=30)).isoformat(),
        "toolName": "analyze_trends",
        "status": "success",
        "result": "Revenue trend: +12.3% QoQ, top region: East",
    },
    {
        "type": "lifecycle",
        "id": "life-2",
        "parentId": "msg-1",
        "timestamp": (now - timedelta(minutes=27, seconds=20)).isoformat(),
        "phase": "end",
    },
    {
        "type": "message",
        "id": "msg-2",
        "parentId": "sess-1",
        "timestamp": (now - timedelta(minutes=27)).isoformat(),
        "message": {
            "role": "assistant",
            "content": "根据分析，2024年Q4销售数据表现良好，总营收560万美元，环比增长12.3%。华东地区表现最佳。",
            "model": "deepseek-v4-pro",
            "provider": "deepseek",
            "usage": {"input": 1250, "output": 320}
        }
    },
]

jsonl_path = agents_dir / f"{session_id}.jsonl"
with open(jsonl_path, "w") as f:
    for evt in events:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")

print(f"Created {len(events)} demo events")
print(f"  JSONL: {jsonl_path}")
print(f"  Meta:  {agents_dir / 'sessions.json'}")
