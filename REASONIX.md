# REASONIX.md — OpenClaw OTel Monitor

## Stack

- **Python 3** — runtime language
- **FastAPI + uvicorn** — HTTP server and REST API ([app.py](src/server/app.py:10))
- **SQLite (stdlib sqlite3)** — metrics storage ([metrics_store.py](src/aggregator/metrics_store.py:1))
- **OpenTelemetry SDK** — metrics export ([requirements.txt](requirements.txt:8))
- **watchdog** — filesystem watching for session JSONL files ([session_collector.py](src/collector/session_collector.py:9))
- **aiohttp** — HTTP client to OpenClaw gateway ([requirements.txt](requirements.txt:4))
- **websockets** — real-time dashboard updates ([api.py](src/server/api.py:276))
- **tomli** — TOML config parsing ([config.py](src/config.py:7))
- **Chart.js (CDN)** — frontend charting ([index.html](src/web/static/index.html:11))

## Layout

- `src/server/` — FastAPI app lifecycle + REST/WebSocket endpoints
- `src/collector/` — data collectors: session JSONL scanner + gateway health poller
- `src/aggregator/` — SQLite metrics store + session/model aggregation logic
- `src/web/static/` — frontend: `index.html`, `style.css`, `js/`
- `config/default.toml` — default configuration (host, port, intervals, paths)
- `tests/` — **empty directory** (no test runner configured)
- `run.py` — entry point (adds project root to `sys.path`, calls `main()`)
- `start.sh` — creates venv, installs deps, runs `python run.py`

## Commands

- **Run** — `python run.py` or `./start.sh`
- **Run as service** — `openclaw-otel-monitor.service` systemd unit provided

> No test, lint, format, or typecheck scripts exist. No `pyproject.toml`, `Makefile`, or `setup.cfg`.

## Conventions

- **Dataclass config** — all config sections are Python dataclasses with defaults matching `config/default.toml` ([config.py](src/config.py:1))
- **Relative imports** — intra-package imports use `..` relative paths (e.g. `from ..config import Config`)
- **Injected globals** — API module receives store/collector/aggregator instances via `set_dependencies()` into module-level `_`-prefixed globals ([api.py](src/server/api.py:64))
- **`__init__.py`** exports `__version__ = "0.1.0"` only
- **Config file path** — `~/.config/openclaw-otel-monitor/config.toml` (optional; falls back to defaults)

## Watch out for

- **No test suite** — `tests/` directory exists but is empty. No pytest config in repo.
- **No type checking** — no `pyproject.toml`, `mypy.ini`, or `.pylintrc`. `src/aggregator/metrics_store.py` uses `Optional[sqlite3.Connection]` which breaks in Python <3.11.
- **Frontend deps via CDN** — Chart.js loaded from `cdn.jsdelivr.net`; no offline fallback.
- **SQLite in append-only mode** — `metrics_store.py` uses `INSERT` with a pending-write buffer + periodic flush; no migration system.
