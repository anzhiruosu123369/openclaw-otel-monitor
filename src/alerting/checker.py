"""Alert checker — runs periodic rule evaluation and stores results."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from .rules import (
    AlertRule, AlertSeverity, RULE_EVALUATORS, get_default_rules,
)

logger = logging.getLogger(__name__)


class AlertRecord:
    """A single alert firing record."""
    def __init__(self, rule: AlertRule, message: str, context: dict):
        self.rule_name = rule.name
        self.rule_type = rule.rule_type.value
        self.severity = rule.severity.value
        self.message = message
        self.timestamp = datetime.now().isoformat()
        self.acknowledged = False


class AlertChecker:
    """Periodically checks alert rules and stores results."""

    def __init__(self, store, collector, gateway_collector, interval: int = 30, config_data: dict = None):
        self._store = store
        self._collector = collector
        self._gateway = gateway_collector
        self._interval = interval
        self._rules = get_default_rules()
        if config_data:
            self.update_rules(config_data)
        self._alerts: List[AlertRecord] = []
        self._max_alerts = 200
        self._running = False
        self._gateway_failures: List[str] = []
        self._last_check: Optional[datetime] = None

    def update_rules(self, config_data: dict):
        """Update rules from config."""
        from .rules import load_rules_from_config
        self._rules = load_rules_from_config(config_data)

    async def run_loop(self):
        """Run the alert check loop."""
        self._running = True
        logger.info(f"Alert checker started (interval={self._interval}s)")
        while self._running:
            try:
                await self._check_once()
            except Exception as e:
                logger.error(f"Alert check error: {e}")
            await asyncio.sleep(self._interval)

    def stop(self):
        self._running = False

    async def _check_once(self):
        """Run all enabled rules against current state."""
        context = await self._build_context()
        self._last_check = datetime.now()

        for rule in self._rules:
            if not rule.enabled:
                continue

            evaluator = RULE_EVALUATORS.get(rule.rule_type)
            if not evaluator:
                continue

            try:
                message = evaluator(context, rule.params)
                if message:
                    self._fire_alert(rule, message, context)
            except Exception as e:
                logger.warning(f"Rule {rule.name} evaluation error: {e}")

        # Track gateway failures for consecutive failure counting
        gateway = context.get("gateway", {})
        if not gateway.get("healthy"):
            self._gateway_failures.append(datetime.now().isoformat())
            # Keep only recent failures (last hour)
            cutoff = datetime.now() - timedelta(hours=1)
            self._gateway_failures = [
                f for f in self._gateway_failures
                if f >= cutoff.isoformat()
            ]
        else:
            # Reset on success
            self._gateway_failures = []

    async def _build_context(self) -> Dict[str, Any]:
        """Collect current state for rule evaluation."""
        context: Dict[str, Any] = {
            "gateway_failures": self._gateway_failures,
        }

        # Gateway status
        if self._gateway:
            context["gateway"] = {
                "healthy": self._gateway.status.healthy,
                "status": self._gateway.status.status,
                "response_time_ms": self._gateway.status.response_time_ms,
            }

        # TPM data
        if self._collector:
            try:
                tpm = await self._collector.get_tpm_stats(hours=1)
                context["tpm"] = tpm
            except Exception:
                pass

            # Stuck sessions (WORKING for >30 min)
            stuck = []
            for sk, state in self._collector.sessions.items():
                if state.status == "WORKING" and state.updated_at:
                    age = (datetime.now() - state.updated_at).total_seconds() / 60
                    if age > 30:
                        stuck.append({
                            "session_key": sk,
                            "agent_id": state.agent_id,
                            "minutes": int(age),
                        })
            context["stuck_sessions"] = stuck

            # Recent errors
            errors = []
            cutoff = datetime.now() - timedelta(minutes=10)
            for sk, state in self._collector.sessions.items():
                for err in state.model_errors:
                    ts = err.get("timestamp")
                    if ts:
                        try:
                            if isinstance(ts, (int, float)):
                                err_dt = datetime.fromtimestamp(ts / 1000)
                            else:
                                err_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if err_dt > cutoff:
                                errors.append(err)
                        except Exception:
                            pass
            context["recent_errors"] = errors

        # Daily cost
        if self._store:
            try:
                from ..cost import compute_cost, USD_TO_CNY
                stats = self._store.get_model_stats(days=1)
                daily_cost_usd = sum(
                    compute_cost(
                        m.get("model", "unknown"),
                        m.get("provider", ""),
                        m.get("total_input_tokens", 0),
                        m.get("total_output_tokens", 0),
                        currency="USD",
                    )
                    for m in stats
                )
                context["daily_cost_cny"] = round(daily_cost_usd * USD_TO_CNY, 2)
            except Exception:
                context["daily_cost_cny"] = 0

        return context

    def _fire_alert(self, rule: AlertRule, message: str, context: dict):
        """Record an alert firing (with dedup: same rule+message within 5 min)."""
        now = datetime.now()

        # Deduplicate: skip if same rule+message within last 5 minutes
        for existing in self._alerts:
            if (existing.rule_type == rule.rule_type.value
                    and existing.message == message):
                try:
                    existing_dt = datetime.fromisoformat(existing.timestamp)
                    if (now - existing_dt).total_seconds() < 300:
                        return  # Skip duplicate
                except Exception:
                    pass

        record = AlertRecord(rule, message, context)
        self._alerts.append(record)

        # Trim old alerts
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

        logger.warning(f"[{rule.severity.value}] {rule.name}: {message}")

        # Store in DB via metrics_store
        if self._store:
            try:
                self._store.record_alert(
                    rule_type=rule.rule_type.value,
                    severity=rule.severity.value,
                    name=rule.name,
                    message=message,
                )
            except Exception as e:
                logger.warning(f"Failed to store alert: {e}")

    def get_alerts(self, unread_only: bool = False, limit: int = 50) -> List[dict]:
        """Get alert history."""
        alerts = self._alerts
        if unread_only:
            alerts = [a for a in alerts if not a.acknowledged]

        return [
            {
                "name": a.rule_name,
                "rule_type": a.rule_type,
                "severity": a.severity,
                "message": a.message,
                "timestamp": a.timestamp,
                "acknowledged": a.acknowledged,
            }
            for a in alerts[-limit:]
        ]

    def acknowledge_alert(self, index: int) -> bool:
        """Mark an alert as acknowledged by index."""
        if 0 <= index < len(self._alerts):
            self._alerts[index].acknowledged = True
            return True
        return False

    def acknowledge_all(self):
        for a in self._alerts:
            a.acknowledged = True
