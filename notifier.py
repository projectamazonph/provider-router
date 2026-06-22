#!/usr/bin/env python3
"""
Notification system for Provider Router.
Sends in-chat notifications via Hermes gateway.
Can be extended to Telegram, Android notifications, etc.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "usage.db"


class Notifier:
    """Sends notifications about provider events."""

    # Event severity levels
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    # Event → severity mapping
    EVENT_SEVERITY = {
        "provider_switched": INFO,
        "key_rotated": INFO,
        "rate_limit_warning": WARNING,
        "provider_exhausted": WARNING,
        "key_exhausted": WARNING,
        "local_fallback_activated": CRITICAL,
        "local_fallback_deactivated": INFO,
        "daily_limit_warning_80pct": WARNING,
        "rpm_warning_80pct": WARNING,
    }

    # Human-readable event messages
    EVENT_MESSAGES = {
        "provider_switched": "🔄 Provider switched: {details}",
        "key_rotated": "🔑 API key rotated: {details}",
        "rate_limit_warning": "⚠️ Rate limit warning: {details}",
        "provider_exhausted": "🚫 Provider exhausted: {details}",
        "key_exhausted": "🚫 API key exhausted: {details}",
        "local_fallback_activated": "🏠 Local LLM activated — all cloud providers exhausted. I'll continue with reduced capability until limits refresh.",
        "local_fallback_deactivated": "☁️ Cloud provider restored — switching back from local LLM.",
        "daily_limit_warning_80pct": "📊 Daily usage at 80%: {details}",
        "rpm_warning_80pct": "📊 Per-minute usage at 80%: {details}",
    }

    def __init__(self):
        self.db = sqlite3.connect(str(DB_PATH))
        self.db.row_factory = sqlite3.Row

    def format_event(self, event_type: str, provider: str, details: str) -> str:
        """Format an event into a human-readable message."""
        severity = self.EVENT_SEVERITY.get(event_type, self.INFO)
        template = self.EVENT_MESSAGES.get(event_type, f"📌 {event_type}: {details}")

        severity_emoji = {
            self.INFO: "ℹ️",
            self.WARNING: "⚠️",
            self.CRITICAL: "🔴",
        }.get(severity, "ℹ️")

        message = template.format(details=details)
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

        return f"[{timestamp}] {severity_emoji} {message}"

    def should_notify(self, event_type: str) -> bool:
        """Check if an event type should trigger a notification."""
        # All events in the mapping should notify
        return event_type in self.EVENT_MESSAGES

    def get_pending_notifications(self, since_id: int = 0) -> list[dict]:
        """Get notifications that haven't been delivered yet."""
        rows = self.db.execute(
            """SELECT * FROM provider_events 
               WHERE id > ? AND event_type IN ({})
               ORDER BY id ASC LIMIT 20""".format(
                ",".join(f"'{e}'" for e in self.EVENT_MESSAGES.keys())
            ),
            (since_id,)
        ).fetchall()

        notifications = []
        for row in rows:
            notifications.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "provider": row["provider"],
                "details": row["details"],
                "message": self.format_event(row["event_type"], row["provider"], row["details"]),
                "severity": self.EVENT_SEVERITY.get(row["event_type"], self.INFO),
            })

        return notifications


if __name__ == "__main__":
    import sys
    notifier = Notifier()

    if len(sys.argv) > 1 and sys.argv[1] == "pending":
        since_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        notifs = notifier.get_pending_notifications(since_id)
        for n in notifs:
            print(f"[{n['id']}] {n['message']}")
    else:
        # Demo: show all event types
        for event_type in notifier.EVENT_MESSAGES:
            print(notifier.format_event(event_type, "demo", "demo details"))
