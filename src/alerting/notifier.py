"""Alert notification channels — webhook, Slack, etc."""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def send_webhook(url: str, payload: dict) -> bool:
    """Send alert to a generic webhook URL."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 400:
                    logger.warning(f"Webhook returned {resp.status}")
                    return False
                return True
    except ImportError:
        logger.warning("aiohttp not available, skipping webhook")
        return False
    except Exception as e:
        logger.warning(f"Webhook error: {e}")
        return False


async def send_slack_webhook(url: str, rule_name: str, severity: str, message: str) -> bool:
    """Send alert to Slack webhook."""
    color_map = {"critical": "danger", "warning": "warning", "info": "good"}
    payload = {
        "attachments": [{
            "color": color_map.get(severity, "good"),
            "title": f"[{severity.upper()}] {rule_name}",
            "text": message,
            "footer": "OpenClaw OTel Monitor",
            "ts": __import__("time").time(),
        }]
    }
    return await send_webhook(url, payload)
