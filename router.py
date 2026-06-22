#!/usr/bin/env python3
"""
Provider Router & Token Usage Tracker for Hermes Agent
======================================================
Tracks usage per key, per provider, per model.
Intelligently routes to the best available provider.
Activates local LLM fallback when all cloud providers are exhausted.
"""

import json
import time
import os
import threading
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "usage.db"
PROVIDER_DB_PATH = BASE_DIR / "provider_db.json"
STATE_PATH = BASE_DIR / "router_state.json"

# ── Load provider database ───────────────────────────────────────────────────
with open(PROVIDER_DB_PATH) as f:
    PROVIDER_DB = json.load(f)

# ── SQLite setup ─────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            key_id TEXT DEFAULT 'default',
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            request_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'success',
            notes TEXT DEFAULT ''
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_state (
            provider TEXT NOT NULL,
            key_id TEXT DEFAULT 'default',
            window_start TEXT NOT NULL,
            window_type TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            exhausted INTEGER DEFAULT 0,
            PRIMARY KEY (provider, key_id, window_start, window_type)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS provider_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            provider TEXT,
            details TEXT DEFAULT ''
        )
    """)
    db.commit()
    return db


class TokenTracker:
    """Tracks token usage per provider/key/model with rate limit awareness."""

    def __init__(self):
        self.db = get_db()
        self._lock = threading.Lock()

    def record_usage(self, provider: str, model: str, input_tokens: int = 0,
                     output_tokens: int = 0, key_id: str = "default",
                     status: str = "success", notes: str = ""):
        """Record a single API call."""
        now = datetime.now(timezone.utc).isoformat()
        total = input_tokens + output_tokens
        with self._lock:
            self.db.execute(
                """INSERT INTO usage_log 
                   (timestamp, provider, model, key_id, input_tokens, output_tokens, total_tokens, status, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, provider, model, key_id, input_tokens, output_tokens, total, status, notes)
            )
            # Update rate limit window counters
            self._increment_window(provider, key_id, "minute", 1, total)
            self._increment_window(provider, key_id, "day", 1, total)
            self.db.commit()

    def _increment_window(self, provider: str, key_id: str, window_type: str,
                          req_count: int, token_count: int):
        now = datetime.now(timezone.utc)
        if window_type == "minute":
            window_start = now.replace(second=0, microsecond=0).isoformat()
        elif window_type == "day":
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        else:
            window_start = now.isoformat()

        self.db.execute(
            """INSERT INTO rate_limit_state (provider, key_id, window_start, window_type, request_count, token_count)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider, key_id, window_start, window_type)
               DO UPDATE SET request_count = request_count + ?, token_count = token_count + ?""",
            (provider, key_id, window_start, window_type, req_count, token_count, req_count, token_count)
        )

    def get_window_usage(self, provider: str, key_id: str = "default",
                         window_type: str = "minute") -> dict:
        """Get current window usage for a provider/key."""
        now = datetime.now(timezone.utc)
        if window_type == "minute":
            window_start = now.replace(second=0, microsecond=0).isoformat()
        elif window_type == "day":
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        else:
            window_start = now.isoformat()

        row = self.db.execute(
            "SELECT request_count, token_count FROM rate_limit_state WHERE provider=? AND key_id=? AND window_start=? AND window_type=?",
            (provider, key_id, window_start, window_type)
        ).fetchone()

        if row:
            return {"requests": row["request_count"], "tokens": row["token_count"]}
        return {"requests": 0, "tokens": 0}

    def is_exhausted(self, provider: str, key_id: str = "default") -> tuple[bool, str]:
        """Check if a provider/key is rate-limited. Returns (exhausted, reason)."""
        provider_info = PROVIDER_DB["providers"].get(provider)
        if not provider_info:
            return False, "unknown provider"

        # Get the tier for this key (default to free)
        tier = self._get_key_tier(provider, key_id)
        limits = provider_info["rate_limits"].get(tier, {})

        # Check per-minute limits
        rpm = limits.get("requests_per_minute")
        if rpm:
            usage = self.get_window_usage(provider, key_id, "minute")
            if usage["requests"] >= rpm:
                return True, f"RPM limit reached ({usage['requests']}/{rpm})"

        # Check per-day limits
        rpd = limits.get("requests_per_day")
        if rpd:
            usage = self.get_window_usage(provider, key_id, "day")
            if usage["requests"] >= rpd:
                return True, f"RPD limit reached ({usage['requests']}/{rpd})"

        # Check token-per-minute limits
        tpm = limits.get("tokens_per_minute")
        if tpm:
            usage = self.get_window_usage(provider, key_id, "minute")
            if usage["tokens"] >= tpm:
                return True, f"TPM limit reached ({usage['tokens']}/{tpm})"

        # Check 80% warning threshold
        if rpm:
            usage = self.get_window_usage(provider, key_id, "minute")
            if usage["requests"] >= rpm * 0.8:
                return False, f"RPM at {usage['requests']}/{rpm} (80% warning)"
        if rpd:
            usage = self.get_window_usage(provider, key_id, "day")
            if usage["requests"] >= rpd * 0.8:
                return False, f"RPD at {usage['requests']}/{rpd} (80% warning)"

        return False, "ok"

    def _get_key_tier(self, provider: str, key_id: str) -> str:
        """Determine the tier for a given key. Override via state file."""
        state = self._load_state()
        tiers = state.get("key_tiers", {})
        return tiers.get(f"{provider}:{key_id}", "free")

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            with open(STATE_PATH) as f:
                return json.load(f)
        return {}

    def get_usage_summary(self, provider: Optional[str] = None) -> dict:
        """Get usage summary for a provider or all providers."""
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        minute_start = now.replace(second=0, microsecond=0).isoformat()

        where = ""
        params = []
        if provider:
            where = "WHERE provider = ?"
            params = [provider]

        # Today's totals
        rows = self.db.execute(
            f"""SELECT provider, model, 
                       SUM(request_count) as total_requests,
                       SUM(input_tokens) as total_input,
                       SUM(output_tokens) as total_output,
                       SUM(total_tokens) as total_tokens
                FROM usage_log {where}
                AND timestamp >= ?
                GROUP BY provider, model""",
            params + [day_start]
        ).fetchall()

        summary = {}
        for row in rows:
            p = row["provider"]
            if p not in summary:
                summary[p] = {"models": {}, "total_requests": 0, "total_tokens": 0}
            summary[p]["models"][row["model"]] = {
                "requests": row["total_requests"],
                "input_tokens": row["total_input"],
                "output_tokens": row["total_output"],
                "total_tokens": row["total_tokens"],
            }
            summary[p]["total_requests"] += row["total_requests"]
            summary[p]["total_tokens"] += row["total_tokens"]

        # Add rate limit status
        for p in summary:
            exhausted, reason = self.is_exhausted(p)
            summary[p]["exhausted"] = exhausted
            summary[p]["status"] = reason

        return summary

    def log_event(self, event_type: str, provider: str = "", details: str = ""):
        """Log a routing event."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.db.execute(
                "INSERT INTO provider_events (timestamp, event_type, provider, details) VALUES (?, ?, ?, ?)",
                (now, event_type, provider, details)
            )
            self.db.commit()

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """Get recent routing events."""
        rows = self.db.execute(
            "SELECT * FROM provider_events ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def reset_windows(self):
        """Reset expired rate limit windows. Called periodically."""
        now = datetime.now(timezone.utc)
        with self._lock:
            # Clean up old minute windows (older than 2 minutes)
            cutoff = (now - timedelta(minutes=2)).isoformat()
            self.db.execute(
                "DELETE FROM rate_limit_state WHERE window_type='minute' AND window_start < ?",
                (cutoff,)
            )
            # Clean up old day windows (older than 2 days)
            cutoff = (now - timedelta(days=2)).isoformat()
            self.db.execute(
                "DELETE FROM rate_limit_state WHERE window_type='day' AND window_start < ?",
                (cutoff,)
            )
            self.db.commit()


class ProviderRouter:
    """Intelligent provider router with automatic fallback."""

    def __init__(self):
        self.tracker = TokenTracker()
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            with open(STATE_PATH) as f:
                return json.load(f)
        return {
            "current_provider": None,
            "current_key_id": "default",
            "exhausted_providers": [],
            "local_active": False,
            "last_switch_reason": "",
            "switch_history": [],
        }

    def _save_state(self):
        with open(STATE_PATH, "w") as f:
            json.dump(self.state, f, indent=2)

    def get_next_provider(self, preferred_model: str = None) -> dict:
        """
        Determine the best available provider.
        Returns: {provider, model, key_id, reason}
        """
        providers_by_priority = sorted(
            PROVIDER_DB["providers"].items(),
            key=lambda x: x[1].get("priority", 99)
        )

        # Check if current provider is still available
        current = self.state.get("current_provider")
        if current and current not in self.state.get("exhausted_providers", []):
            exhausted, reason = self.tracker.is_exhausted(current)
            if not exhausted:
                return {
                    "provider": current,
                    "model": preferred_model or self._get_default_model(current),
                    "key_id": self.state.get("current_key_id", "default"),
                    "reason": "current provider still available",
                }
            else:
                self._mark_exhausted(current, reason)

        # Try each provider in priority order
        for provider_name, provider_info in providers_by_priority:
            if provider_name in self.state.get("exhausted_providers", []):
                continue
            if provider_name == "local":
                continue  # Local is last resort

            # Check all keys for this provider
            keys = self._get_keys_for_provider(provider_name)
            for key_id in keys:
                exhausted, reason = self.tracker.is_exhausted(provider_name, key_id)
                if not exhausted:
                    self._switch_to(provider_name, key_id, f"selected from priority list")
                    return {
                        "provider": provider_name,
                        "model": preferred_model or self._get_default_model(provider_name),
                        "key_id": key_id,
                        "reason": f"selected from priority list (key: {key_id})",
                    }
                else:
                    self.tracker.log_event("key_exhausted", provider_name, f"key={key_id}: {reason}")

        # All cloud providers exhausted — activate local
        self._activate_local()
        return {
            "provider": "local",
            "model": "gemma-3-4b-it",
            "key_id": "default",
            "reason": "all cloud providers exhausted, local fallback activated",
        }

    def _get_keys_for_provider(self, provider: str) -> list[str]:
        """Get all API keys configured for a provider."""
        state = self.state
        keys = state.get("keys", {}).get(provider, {})
        if not keys:
            return ["default"]
        return list(keys.keys())

    def _get_default_model(self, provider: str) -> str:
        """Get the default model for a provider."""
        provider_info = PROVIDER_DB["providers"].get(provider, {})
        models = provider_info.get("models", {})
        if models:
            return list(models.keys())[0]
        return "unknown"

    def _switch_to(self, provider: str, key_id: str, reason: str):
        """Switch to a new provider."""
        old_provider = self.state.get("current_provider")
        self.state["current_provider"] = provider
        self.state["current_key_id"] = key_id
        self.state["local_active"] = False
        self.state["last_switch_reason"] = reason
        self.state["switch_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from": old_provider,
            "to": provider,
            "key_id": key_id,
            "reason": reason,
        })
        # Keep only last 50 switches
        self.state["switch_history"] = self.state["switch_history"][-50:]
        self._save_state()
        self.tracker.log_event("provider_switched", provider,
                               f"from={old_provider}, key={key_id}, reason={reason}")

    def _mark_exhausted(self, provider: str, reason: str):
        """Mark a provider as exhausted."""
        if provider not in self.state.get("exhausted_providers", []):
            self.state["exhausted_providers"].append(provider)
            self._save_state()
            self.tracker.log_event("provider_exhausted", provider, reason)

    def _activate_local(self):
        """Activate local LLM fallback."""
        if not self.state.get("local_active"):
            self.state["local_active"] = True
            self.state["current_provider"] = "local"
            self._save_state()
            self.tracker.log_event("local_fallback_activated", "local",
                                   "all cloud providers exhausted")

    def report_usage(self, provider: str, model: str, input_tokens: int = 0,
                     output_tokens: int = 0, key_id: str = "default",
                     status: str = "success", notes: str = ""):
        """Report usage and check if we need to switch."""
        self.tracker.record_usage(provider, model, input_tokens, output_tokens,
                                  key_id, status, notes)

        # Check if current provider just got exhausted
        if provider != "local":
            exhausted, reason = self.tracker.is_exhausted(provider, key_id)
            if exhausted:
                self._mark_exhausted(provider, reason)
                self.tracker.log_event("rate_limit_warning", provider, reason)

    def get_status(self) -> dict:
        """Get full router status."""
        summary = self.tracker.get_usage_summary()
        events = self.tracker.get_recent_events(10)

        return {
            "current_provider": self.state.get("current_provider"),
            "current_key_id": self.state.get("current_key_id"),
            "local_active": self.state.get("local_active", False),
            "exhausted_providers": self.state.get("exhausted_providers", []),
            "last_switch_reason": self.state.get("last_switch_reason", ""),
            "usage_summary": summary,
            "recent_events": events,
        }

    def reset_exhausted(self, provider: str = None):
        """Reset exhausted status (e.g., after rate limit window resets)."""
        if provider:
            if provider in self.state.get("exhausted_providers", []):
                self.state["exhausted_providers"].remove(provider)
        else:
            self.state["exhausted_providers"] = []
        self._save_state()

    def add_key(self, provider: str, key_id: str, api_key: str, tier: str = "free"):
        """Add an API key to the pool."""
        if "keys" not in self.state:
            self.state["keys"] = {}
        if provider not in self.state["keys"]:
            self.state["keys"][provider] = {}
        self.state["keys"][provider][key_id] = {
            "api_key": api_key,
            "tier": tier,
            "added": datetime.now(timezone.utc).isoformat(),
        }
        if "key_tiers" not in self.state:
            self.state["key_tiers"] = {}
        self.state["key_tiers"][f"{provider}:{key_id}"] = tier
        self._save_state()


# ── CLI interface ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    router = ProviderRouter()

    if len(sys.argv) < 2:
        print("Usage: python3 router.py <command> [args]")
        print("Commands: status, next, report, events, reset, add-key, summary")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        import pprint
        pprint.pprint(router.get_status())

    elif cmd == "next":
        model = sys.argv[2] if len(sys.argv) > 2 else None
        result = router.get_next_provider(model)
        print(json.dumps(result, indent=2))

    elif cmd == "report":
        # Usage: report <provider> <model> <input_tokens> <output_tokens> [key_id]
        provider = sys.argv[2]
        model = sys.argv[3]
        in_tok = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        out_tok = int(sys.argv[5]) if len(sys.argv) > 5 else 0
        key_id = sys.argv[6] if len(sys.argv) > 6 else "default"
        router.report_usage(provider, model, in_tok, out_tok, key_id)
        print(f"Recorded: {provider}/{model} {in_tok+out_tok} tokens (key={key_id})")

    elif cmd == "events":
        events = router.tracker.get_recent_events(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        for e in events:
            print(f"[{e['timestamp']}] {e['event_type']}: {e['provider']} — {e['details']}")

    elif cmd == "reset":
        provider = sys.argv[2] if len(sys.argv) > 2 else None
        router.reset_exhausted(provider)
        print(f"Reset exhausted status for: {provider or 'all providers'}")

    elif cmd == "summary":
        provider = sys.argv[2] if len(sys.argv) > 2 else None
        summary = router.tracker.get_usage_summary(provider)
        print(json.dumps(summary, indent=2))

    elif cmd == "add-key":
        # Usage: add-key <provider> <key_id> <api_key> [tier]
        provider = sys.argv[2]
        key_id = sys.argv[3]
        api_key = sys.argv[4]
        tier = sys.argv[5] if len(sys.argv) > 5 else "free"
        router.add_key(provider, key_id, api_key, tier)
        print(f"Added key '{key_id}' for {provider} (tier={tier})")

    else:
        print(f"Unknown command: {cmd}")
