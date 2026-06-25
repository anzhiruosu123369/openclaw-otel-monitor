"""Alert rules definitions and configuration."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertRuleType(Enum):
    GATEWAY_DOWN = "gateway_down"
    TPM_HIGH = "tpm_high"
    ERROR_RATE_HIGH = "error_rate_high"
    SESSION_STUCK = "session_stuck"
    COST_SPIKE = "cost_spike"


@dataclass
class AlertRule:
    """A single alert rule definition."""
    rule_type: AlertRuleType
    name: str
    description: str
    severity: AlertSeverity
    enabled: bool = True
    # Rule-specific params
    params: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self, context: Dict[str, Any]) -> Optional[str]:
        """Evaluate this rule against current state. Returns None if OK, message if triggered."""
        raise NotImplementedError


@dataclass
class GatewayDownRule(AlertRule):
    """Alert when gateway is unhealthy or unreachable."""

    def __init__(self, max_failures: int = 2):
        super().__init__(
            rule_type=AlertRuleType.GATEWAY_DOWN,
            name="Gateway 离线",
            description="OpenClaw Gateway 连续检查失败",
            severity=AlertSeverity.CRITICAL,
            params={"max_failures": max_failures},
        )

    @classmethod
    def evaluate_rule(cls, context: Dict[str, Any], params: Dict) -> Optional[str]:
        gateway = context.get("gateway", {})
        failures = len(context.get("gateway_failures", []))
        max_fail = params.get("max_failures", 2)
        if not gateway.get("healthy") and failures >= max_fail:
            return f"Gateway 已离线 (连续 {failures} 次检查失败, 状态: {gateway.get('status', 'unknown')})"
        return None


@dataclass
class TPMHighRule(AlertRule):
    """Alert when TPM approaches rate limit."""

    def __init__(self, threshold_pct: float = 80.0):
        super().__init__(
            rule_type=AlertRuleType.TPM_HIGH,
            name="TPM 接近限流",
            description="TPM 使用率超过阈值",
            severity=AlertSeverity.WARNING,
            params={"threshold_pct": threshold_pct},
        )

    @classmethod
    def evaluate_rule(cls, context: Dict[str, Any], params: Dict) -> Optional[str]:
        tpm_data = context.get("tpm", {})
        rate_limit = tpm_data.get("rate_limit", {})
        peak = rate_limit.get("peak_tpm", 0)
        current = rate_limit.get("current_tpm", 0)
        threshold = params.get("threshold_pct", 80.0)
        # Check current TPM
        if current > 0:
            # Compare with configured rate limit (default 100000)
            rate_limit_max = params.get("rate_limit_max", 100000)
            pct = (current / rate_limit_max) * 100
            if pct >= threshold:
                return f"当前 TPM {current} 已达限流 {rate_limit_max} 的 {pct:.0f}%"
        return None


@dataclass
class ErrorRateHighRule(AlertRule):
    """Alert when model error rate spikes."""

    def __init__(self, threshold: int = 5, window_minutes: int = 10):
        super().__init__(
            rule_type=AlertRuleType.ERROR_RATE_HIGH,
            name="错误率过高",
            description="模型错误数量超过阈值",
            severity=AlertSeverity.WARNING,
            params={"threshold": threshold, "window_minutes": window_minutes},
        )

    @classmethod
    def evaluate_rule(cls, context: Dict[str, Any], params: Dict) -> Optional[str]:
        recent_errors = context.get("recent_errors", [])
        threshold = params.get("threshold", 5)
        window = params.get("window_minutes", 10)
        if len(recent_errors) >= threshold:
            return f"最近 {window} 分钟内发生 {len(recent_errors)} 次模型错误 (阈值: {threshold})"
        return None


@dataclass
class SessionStuckRule(AlertRule):
    """Alert when a session stays in WORKING state too long."""

    def __init__(self, max_minutes: int = 30):
        super().__init__(
            rule_type=AlertRuleType.SESSION_STUCK,
            name="会话卡住",
            description="会话长时间处于运行中状态",
            severity=AlertSeverity.WARNING,
            params={"max_minutes": max_minutes},
        )

    @classmethod
    def evaluate_rule(cls, context: Dict[str, Any], params: Dict) -> Optional[str]:
        stuck_sessions = context.get("stuck_sessions", [])
        max_min = params.get("max_minutes", 30)
        if stuck_sessions:
            names = [s.get("session_key", "?") for s in stuck_sessions[:3]]
            extra = f"等 {len(stuck_sessions)} 个" if len(stuck_sessions) > 3 else ""
            return f"{len(stuck_sessions)} 个会话运行超过 {max_min} 分钟: {', '.join(names[:3])} {extra}"
        return None


@dataclass
class CostSpikeRule(AlertRule):
    """Alert when daily cost exceeds threshold."""

    def __init__(self, daily_threshold_cny: float = 100.0):
        super().__init__(
            rule_type=AlertRuleType.COST_SPIKE,
            name="费用超支",
            description="当日费用超过预算阈值",
            severity=AlertSeverity.WARNING,
            params={"daily_threshold_cny": daily_threshold_cny},
        )

    @classmethod
    def evaluate_rule(cls, context: Dict[str, Any], params: Dict) -> Optional[str]:
        daily_cost = context.get("daily_cost_cny", 0)
        threshold = params.get("daily_threshold_cny", 100)
        if daily_cost >= threshold:
            return f"当日费用 ￥{daily_cost:.2f} 超过阈值 ￥{threshold:.2f}"
        return None


# Registry: rule_type -> evaluate function
RULE_EVALUATORS: Dict[AlertRuleType, Callable] = {
    AlertRuleType.GATEWAY_DOWN: GatewayDownRule.evaluate_rule,
    AlertRuleType.TPM_HIGH: TPMHighRule.evaluate_rule,
    AlertRuleType.ERROR_RATE_HIGH: ErrorRateHighRule.evaluate_rule,
    AlertRuleType.SESSION_STUCK: SessionStuckRule.evaluate_rule,
    AlertRuleType.COST_SPIKE: CostSpikeRule.evaluate_rule,
}


def get_default_rules() -> List[AlertRule]:
    """Return default set of alert rules."""
    return [
        GatewayDownRule(max_failures=2),
        TPMHighRule(threshold_pct=80),
        ErrorRateHighRule(threshold=5, window_minutes=10),
        SessionStuckRule(max_minutes=30),
        CostSpikeRule(daily_threshold_cny=100),
    ]


def load_rules_from_config(config_data: dict) -> List[AlertRule]:
    """Load alert rules from config dict (parsed TOML)."""
    rules = get_default_rules()
    alert_config = config_data.get("alerting", {})
    if not alert_config:
        return rules

    # Override defaults from config
    for rule in rules:
        rule_type_name = rule.rule_type.value
        if rule_type_name in alert_config:
            rule.enabled = alert_config[rule_type_name].get("enabled", rule.enabled)
            rule.params.update(alert_config[rule_type_name].get("params", {}))

    # Notification config
    rules_config = config_data.get("alerting", {})
    return rules
