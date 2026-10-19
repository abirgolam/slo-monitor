"""Alert state machine: emit events only when an alert changes state.

Logging "still firing" every second is noise and leads to alert fatigue.
Only the FIRING and RESOLVED transitions are sent to the log and the webhook.
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger("slo_monitor.alerts")


class AlertManager:
    def __init__(self, webhook_url: str | None = None, sender=None):
        self.webhook_url = webhook_url
        self._send = sender or self._post_webhook
        self.active: dict[tuple[str, str, str], dict] = {}   # (target, slo, severity) -> details

    def update(self, target: str, slo: str, severity: str, firing: bool, details: dict) -> str | None:
        key = (target, slo, severity)
        was_firing = key in self.active
        if firing and not was_firing:
            self.active[key] = details
            self._emit("FIRING", key, details)
            return "FIRING"
        if not firing and was_firing:
            self.active.pop(key)
            self._emit("RESOLVED", key, details)
            return "RESOLVED"
        if firing:
            self.active[key] = details   # refresh numbers, no new notification
        return None

    def _emit(self, state: str, key: tuple[str, str, str], details: dict) -> None:
        target, slo, severity = key
        event = {"state": state, "target": target, "slo": slo, "severity": severity, **details}
        log.warning(json.dumps(event))
        if self.webhook_url:
            text = (f"[{state}] {severity.upper()}: {target}/{slo} burning error budget "
                    f"at {details.get('long_burn')}x (long) / {details.get('short_burn')}x (short). "
                    f"Runbook: docs/RUNBOOK.md")
            try:
                self._send(self.webhook_url, {"text": text, "event": event})
            except Exception as e:  # a broken webhook must never kill the monitor
                log.error("webhook delivery failed: %s", e)

    @staticmethod
    def _post_webhook(url: str, payload: dict) -> None:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
