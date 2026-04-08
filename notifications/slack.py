"""
Slack webhook integration for the Meta Ads Management System.

Sends formatted notifications for ad kills, budget changes, winner
celebrations, daily reports, and general alerts via Slack Block Kit.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from config.settings import SLACK_WEBHOOK_URL, CURRENCY

logger = logging.getLogger(__name__)

# Severity-to-colour mapping (Slack attachment hex colours)
_SEVERITY_COLOURS: Dict[str, str] = {
    "critical": "#FF0000",   # red
    "warning": "#FFC107",    # yellow
    "info": "#2196F3",       # blue
    "positive": "#4CAF50",   # green
}


class SlackNotifier:
    """Send notifications to Slack via an incoming webhook.

    All public methods degrade gracefully when ``SLACK_WEBHOOK_URL`` is not
    configured: they log a warning and return ``False`` instead of raising.
    """

    def __init__(self, webhook_url: Optional[str] = None) -> None:
        self._webhook_url = webhook_url or SLACK_WEBHOOK_URL

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_configured(self) -> bool:
        """Return True if a webhook URL is available."""
        if not self._webhook_url:
            logger.warning(
                "Slack webhook URL not configured. "
                "Set SLACK_WEBHOOK_URL in your .env file to enable Slack notifications."
            )
            return False
        return True

    def _post(self, payload: Dict[str, Any]) -> bool:
        """POST a JSON payload to the webhook URL.

        Returns True on success, False on failure (never raises).
        """
        if not self._is_configured():
            return False

        try:
            resp = requests.post(
                self._webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(
                    "Slack webhook returned %d: %s", resp.status_code, resp.text
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.error("Failed to send Slack message: %s", exc)
            return False

    @staticmethod
    def _build_blocks(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build a list of Slack Block Kit block objects.

        Each item in *sections* is a dict with at least a ``"type"`` key.
        Recognised convenience types:

        - ``{"type": "header", "text": "..."}``
        - ``{"type": "section", "text": "..."}``
        - ``{"type": "fields", "fields": ["col1", "col2", ...]}``
        - ``{"type": "divider"}``
        - ``{"type": "context", "text": "..."}``

        Unknown types are passed through as-is for full Block Kit control.
        """
        blocks: List[Dict[str, Any]] = []
        for s in sections:
            block_type = s.get("type", "section")

            if block_type == "header":
                blocks.append({
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": s.get("text", ""),
                        "emoji": True,
                    },
                })
            elif block_type == "section":
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": s.get("text", ""),
                    },
                })
            elif block_type == "fields":
                fields = s.get("fields", [])
                blocks.append({
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f} for f in fields
                    ],
                })
            elif block_type == "divider":
                blocks.append({"type": "divider"})
            elif block_type == "context":
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": s.get("text", "")},
                    ],
                })
            else:
                # Pass through raw block
                blocks.append(s)

        return blocks

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_message(self, text: str, channel: Optional[str] = None) -> bool:
        """Send a plain text message to Slack.

        Args:
            text: The message body (supports Slack mrkdwn).
            channel: Optional channel override (requires a bot token, not
                     supported with simple webhooks but included for
                     forward compatibility).

        Returns:
            True if the message was sent successfully.
        """
        payload: Dict[str, Any] = {"text": text}
        if channel:
            payload["channel"] = channel
        return self._post(payload)

    def send_report(
        self,
        report_text: str,
        title: str = "Daily Report",
    ) -> bool:
        """Send a formatted report with a title header.

        Args:
            report_text: The report body (plain text or mrkdwn).
            title: Header line displayed above the report.

        Returns:
            True if the message was sent successfully.
        """
        blocks = self._build_blocks([
            {"type": "header", "text": title},
            {"type": "divider"},
            {"type": "section", "text": report_text},
            {"type": "divider"},
            {"type": "context", "text": "Meta Ads Management System"},
        ])
        return self._post({"text": title, "blocks": blocks})

    def send_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "warning",
    ) -> bool:
        """Send a colour-coded alert.

        Args:
            alert_type: Short label (e.g. ``"creative_fatigue"``).
            message: Human-readable alert description.
            severity: One of ``"critical"``, ``"warning"``, ``"info"``,
                      ``"positive"``.

        Returns:
            True if the message was sent successfully.
        """
        colour = _SEVERITY_COLOURS.get(severity, _SEVERITY_COLOURS["info"])
        severity_label = severity.upper()

        payload: Dict[str, Any] = {
            "text": f"[{severity_label}] {alert_type}: {message}",
            "attachments": [
                {
                    "color": colour,
                    "blocks": self._build_blocks([
                        {
                            "type": "section",
                            "text": (
                                f"*[{severity_label}] {alert_type}*\n{message}"
                            ),
                        },
                    ]),
                }
            ],
        }
        return self._post(payload)

    def send_kill_notification(
        self,
        ad_name: str,
        ad_id: str,
        reason: str,
        metrics: Dict[str, Any],
    ) -> bool:
        """Notify that an ad has been killed (paused).

        Args:
            ad_name: Display name of the ad.
            ad_id: Meta ad ID.
            reason: Human-readable kill reason.
            metrics: Dict of key metrics at time of kill (spend, CPA, ROAS, etc.).

        Returns:
            True if the message was sent successfully.
        """
        metric_fields = [
            f"*Spend:* {CURRENCY} {metrics.get('spend', 0):.2f}",
            f"*CPA:* {CURRENCY} {metrics.get('cpa', 0):.2f}",
            f"*ROAS:* {metrics.get('roas', 0):.2f}x",
            f"*Conversions:* {metrics.get('conversions', 0)}",
            f"*CTR:* {metrics.get('ctr', 0):.2%}",
            f"*Impressions:* {metrics.get('impressions', 0):,}",
        ]

        blocks = self._build_blocks([
            {"type": "header", "text": "Ad Killed"},
            {
                "type": "section",
                "text": f"*{ad_name}*\n`{ad_id}`\n\n*Reason:* {reason}",
            },
            {"type": "divider"},
            {"type": "fields", "fields": metric_fields},
            {"type": "context", "text": "Auto-kill by Rules Engine"},
        ])

        return self._post({
            "text": f"Ad Killed: {ad_name} — {reason}",
            "attachments": [
                {
                    "color": _SEVERITY_COLOURS["critical"],
                    "blocks": blocks,
                }
            ],
        })

    def send_scale_notification(
        self,
        entity_name: str,
        entity_id: str,
        old_budget: float,
        new_budget: float,
        reason: str,
    ) -> bool:
        """Notify a budget change (scale up or down).

        Args:
            entity_name: Display name of the campaign / ad set.
            entity_id: Meta entity ID.
            old_budget: Previous daily budget.
            new_budget: New daily budget.
            reason: Why the budget was changed.

        Returns:
            True if the message was sent successfully.
        """
        change_pct = (
            ((new_budget - old_budget) / old_budget * 100) if old_budget else 0
        )
        direction = "increased" if new_budget > old_budget else "decreased"

        blocks = self._build_blocks([
            {"type": "header", "text": f"Budget {direction.title()}"},
            {
                "type": "section",
                "text": (
                    f"*{entity_name}*\n`{entity_id}`\n\n*Reason:* {reason}"
                ),
            },
            {"type": "divider"},
            {
                "type": "fields",
                "fields": [
                    f"*Old Budget:* {CURRENCY} {old_budget:.2f}",
                    f"*New Budget:* {CURRENCY} {new_budget:.2f}",
                    f"*Change:* {change_pct:+.1f}%",
                ],
            },
            {"type": "context", "text": "Budget adjustment by Rules Engine"},
        ])

        colour = (
            _SEVERITY_COLOURS["positive"]
            if new_budget > old_budget
            else _SEVERITY_COLOURS["warning"]
        )

        return self._post({
            "text": (
                f"Budget {direction} for {entity_name}: "
                f"{CURRENCY} {old_budget:.2f} -> {CURRENCY} {new_budget:.2f}"
            ),
            "attachments": [{"color": colour, "blocks": blocks}],
        })

    def send_winner_notification(
        self,
        ad_name: str,
        ad_id: str,
        metrics: Dict[str, Any],
    ) -> bool:
        """Celebrate a new winning creative.

        Args:
            ad_name: Display name of the ad.
            ad_id: Meta ad ID.
            metrics: Performance metrics (CPA, ROAS, conversions, etc.).

        Returns:
            True if the message was sent successfully.
        """
        metric_fields = [
            f"*CPA:* {CURRENCY} {metrics.get('cpa', 0):.2f}",
            f"*ROAS:* {metrics.get('roas', 0):.2f}x",
            f"*Conversions:* {metrics.get('conversions', 0)}",
            f"*Spend:* {CURRENCY} {metrics.get('spend', 0):.2f}",
            f"*CTR:* {metrics.get('ctr', 0):.2%}",
            f"*Hook Rate:* {metrics.get('hook_rate', 0):.1%}",
        ]

        blocks = self._build_blocks([
            {"type": "header", "text": "New Winner Found!"},
            {
                "type": "section",
                "text": (
                    f"*{ad_name}*\n`{ad_id}`\n\n"
                    "This creative is outperforming the current best. "
                    "Consider graduating it to the scale campaign."
                ),
            },
            {"type": "divider"},
            {"type": "fields", "fields": metric_fields},
            {"type": "context", "text": "Winner detected by Rules Engine"},
        ])

        return self._post({
            "text": f"New Winner: {ad_name}",
            "attachments": [
                {
                    "color": _SEVERITY_COLOURS["positive"],
                    "blocks": blocks,
                }
            ],
        })


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_notifier: Optional[SlackNotifier] = None


def get_notifier() -> SlackNotifier:
    """Return a module-level singleton ``SlackNotifier``."""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = SlackNotifier()
    return _default_notifier
