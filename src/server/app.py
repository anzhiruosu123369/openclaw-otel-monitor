"""Main application entry point."""

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ..config import Config
from ..collector.session_collector import SessionCollector
from ..collector.gateway_collector import GatewayCollector
from ..aggregator.metrics_store import MetricsStore
from ..aggregator.session_aggregator import SessionAggregator
from ..aggregator.model_aggregator import ModelAggregator
from ..alerting.checker import AlertChecker
from .api import router, set_dependencies, broadcast_update

logger = logging.getLogger(__name__)


# Global instances
_config: Config = None
_store: MetricsStore = None
_session_collector: SessionCollector = None
_gateway_collector: GatewayCollector = None
_session_aggregator: SessionAggregator = None
_model_aggregator: ModelAggregator = None
_alert_checker: AlertChecker = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _config, _store, _session_collector, _gateway_collector, _session_aggregator, _model_aggregator, _alert_checker

    logger.info("Starting OpenClaw OTel Monitor...")

    # Load config
    config_path = Path.home() / ".config" / "openclaw-otel-monitor" / "config.toml"
    _config = Config.load(str(config_path) if config_path.exists() else None)

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, _config.logging.level),
        format=_config.logging.format,
    )

    # Initialize components
    _store = MetricsStore(_config.metrics_db_path)
    _session_collector = SessionCollector(_config.openclaw_root_path)
    _gateway_collector = GatewayCollector(_config.openclaw.gateway_host, _config.openclaw.gateway_port)
    _session_aggregator = SessionAggregator()
    _model_aggregator = ModelAggregator()

    # Set API dependencies
    set_dependencies(_store, _session_collector, _gateway_collector, _session_aggregator, _model_aggregator)

    # Initialize alert checker
    _alert_checker = AlertChecker(_store, _session_collector, _gateway_collector, interval=30)
    set_dependencies(_store, _session_collector, _gateway_collector, _session_aggregator, _model_aggregator, _alert_checker)

    # Setup callbacks
    async def on_session_update(event_type, data):
        if event_type == "session_update":
            # Update aggregators
            _session_aggregator.update_from_sessions(_session_collector.sessions)
            _model_aggregator.update_from_sessions(_session_collector.sessions)
            # Store session and token data (with deduplication)
            if hasattr(data, '__dict__'):
                _store.upsert_session(data.__dict__)
                # Store token usage with session_key for deduplication
                if hasattr(data, 'token_usage'):
                    session_key = data.session_key if hasattr(data, 'session_key') else None
                    for usage in data.token_usage:
                        _store.record_model_call(
                            model=usage.get("model", "unknown"),
                            provider=usage.get("provider", "unknown"),
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            session_key=session_key,
                            timestamp=usage.get("timestamp"),
                        )
            # Broadcast to WebSocket clients
            await broadcast_update("session_update", {
                "session_key": data.session_key if hasattr(data, 'session_key') else None,
                "status": data.status if hasattr(data, 'status') else None,
            })

    async def on_gateway_status(event_type, data):
        # Record metric
        _store.record_metric("gateway_health", 1.0 if data.healthy else 0.0)
        _store.record_metric("gateway_response_time_ms", data.response_time_ms)
        await broadcast_update("gateway_status", {
            "healthy": data.healthy,
            "status": data.status,
        })

    _session_collector.add_callback(on_session_update)
    _gateway_collector.add_callback(on_gateway_status)

    # Start background tasks
    tasks = []

    async def session_scanner():
        """Periodically scan sessions."""
        while True:
            try:
                await _session_collector.scan_all_sessions()
                _session_aggregator.update_from_sessions(_session_collector.sessions)
                _model_aggregator.update_from_sessions(_session_collector.sessions)

                # Update DB stats
                db_stats = _store.get_model_stats()
                _model_aggregator.update_from_db_stats(db_stats)

            except Exception as e:
                logger.error(f"Session scan error: {e}")

            await asyncio.sleep(_config.collector.session_scan_interval)

    async def gateway_monitor():
        """Monitor gateway health."""
        while True:
            try:
                await _gateway_collector.check_health()
            except Exception as e:
                logger.error(f"Gateway monitor error: {e}")

            await asyncio.sleep(_config.collector.health_check_interval)

    # Initial scan
    await _session_collector.scan_all_sessions()
    _session_aggregator.update_from_sessions(_session_collector.sessions)

    # Start file watcher
    _session_collector.start_watching()

    # Start background tasks
    tasks.append(asyncio.create_task(session_scanner()))
    tasks.append(asyncio.create_task(gateway_monitor()))
    tasks.append(asyncio.create_task(_alert_checker.run_loop()))

    logger.info(f"Monitor started on http://{_config.server.host}:{_config.server.port}")

    yield

    # Cleanup
    logger.info("Shutting down...")

    for task in tasks:
        task.cancel()

    _session_collector.stop_watching()
    await _gateway_collector.close()
    _alert_checker.stop()
    _store.close()


def create_app(config: Config = None) -> FastAPI:
    """Create FastAPI application."""

    app = FastAPI(
        title="OpenClaw OTel Monitor",
        description="Web-based monitoring for OpenClaw",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include API router
    app.include_router(router, prefix="/api")

    # Mount static files
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Root endpoint - serve dashboard
    @app.get("/")
    async def root():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "OpenClaw OTel Monitor API"}

    return app


# Default app instance
app = create_app()


def main():
    """Run the server."""
    import uvicorn

    config = Config.load()

    uvicorn.run(
        "src.server.app:app",
        host=config.server.host,
        port=config.server.port,
        reload=False,
    )


if __name__ == "__main__":
    main()