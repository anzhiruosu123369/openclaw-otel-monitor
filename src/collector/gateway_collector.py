"""Gateway data collector via HTTP API."""

import asyncio
import aiohttp
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class GatewayStatus:
    """Gateway health and status."""
    healthy: bool = False
    status: str = "unknown"  # live, dead, unknown
    last_check: Optional[datetime] = None
    response_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class GatewayMetrics:
    """Gateway metrics snapshot."""
    connections: int = 0
    agents_running: int = 0
    messages_total: int = 0
    tokens_total: int = 0
    uptime_seconds: float = 0.0


class GatewayCollector:
    """Collects data from OpenClaw Gateway via HTTP API."""

    def __init__(self, gateway_host: str, gateway_port: int):
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.status = GatewayStatus()
        self.metrics = GatewayMetrics()
        self._callbacks: list = []
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.gateway_host}:{self.gateway_port}"

    def add_callback(self, callback: callable):
        """Add a callback for status changes."""
        self._callbacks.append(callback)

    async def _notify_callbacks(self, event_type: str, data: Any):
        """Notify all callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_type, data)
                else:
                    callback(event_type, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def check_health(self) -> GatewayStatus:
        """Check gateway health endpoint."""
        url = f"{self.base_url}/health"
        start_time = datetime.now()

        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                response_time = (datetime.now() - start_time).total_seconds() * 1000

                if resp.status == 200:
                    data = await resp.json()
                    self.status = GatewayStatus(
                        healthy=True,
                        status=data.get("status", "live"),
                        last_check=datetime.now(),
                        response_time_ms=response_time,
                    )
                else:
                    self.status = GatewayStatus(
                        healthy=False,
                        status="error",
                        last_check=datetime.now(),
                        response_time_ms=response_time,
                        error=f"HTTP {resp.status}",
                    )
        except asyncio.TimeoutError:
            self.status = GatewayStatus(
                healthy=False,
                status="timeout",
                last_check=datetime.now(),
                error="Connection timeout",
            )
        except aiohttp.ClientError as e:
            self.status = GatewayStatus(
                healthy=False,
                status="error",
                last_check=datetime.now(),
                error=str(e),
            )
        except Exception as e:
            logger.error(f"Health check error: {e}")
            self.status = GatewayStatus(
                healthy=False,
                status="error",
                last_check=datetime.now(),
                error=str(e),
            )

        await self._notify_callbacks("gateway_status", self.status)
        return self.status

    async def get_status(self) -> Optional[Dict[str, Any]]:
        """Get gateway status via API."""
        url = f"{self.base_url}/status"
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error(f"Status fetch error: {e}")
        return None

    async def get_agents_status(self) -> Optional[Dict[str, Any]]:
        """Get agents status from gateway."""
        url = f"{self.base_url}/api/agents"
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.debug(f"Agents status fetch error: {e}")
        return None

    async def start_monitoring(self, interval_seconds: int = 10):
        """Start periodic health checks."""
        self._running = True
        while self._running:
            try:
                await self.check_health()

                # Try to get more detailed status
                status_data = await self.get_status()
                if status_data:
                    # Extract metrics if available
                    self.metrics.connections = status_data.get("connections", 0)
                    self.metrics.agents_running = status_data.get("agentsRunning", 0)
                    await self._notify_callbacks("gateway_metrics", self.metrics)

            except Exception as e:
                logger.error(f"Monitoring error: {e}")

            await asyncio.sleep(interval_seconds)

    def stop_monitoring(self):
        """Stop periodic monitoring."""
        self._running = False

    async def close(self):
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
