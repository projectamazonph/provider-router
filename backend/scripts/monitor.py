"""
Provider Router — Background Monitor Agent.

This script is designed to run as a Hermes cron job. It:
1. Checks all provider statuses (rate limits, credential exhaustion)
2. Detects when the active provider is about to hit limits
3. Proactively switches to the best available provider
4. Notifies the user of events
5. Manages the local LLM server lifecycle

Run via: hermes cron create "every 2m" "provider-router-check"
Or directly: python -m backend.scripts.monitor
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# Setup paths
PROJECT_DIR = Path(__file__).parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.router_engine import (
    ProviderRouterOrchestrator,
    TokenUsageMonitor,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("provider-router-monitor")


def get_hermes_home() -> Path:
    val = (os.environ.get("HERMES_HOME") or "").strip()
    return Path(val) if val else Path.home() / ".hermes"


def run_check():
    """Run a single monitoring check."""
    orch = ProviderRouterOrchestrator()
    status = orch.get_status()

    providers = status.get("providers", {})
    active = status.get("active_provider")
    notifications_sent = []

    for name, data in providers.items():
        state = data.get("state", {})
        creds = data.get("credentials", {})

        # Check 1: All credentials exhausted
        if creds.get("total", 0) > 0 and creds.get("active", 0) == 0:
            if state.get("status") != "exhausted":
                orch.router.report_error(name, 429, "All credentials exhausted")
                orch.notifier.notify(
                    "provider_exhausted",
                    f"⚠️ Provider {name} — all {creds['total']} credential(s) exhausted!",
                    severity="critical",
                    details={"provider": name, "credentials_total": creds["total"]},
                )
                notifications_sent.append(f"exhausted:{name}")

        # Check 2: Rate limited
        elif state.get("status") == "rate_limit":
            reset_at = state.get("rate_limit_reset_at")
            if reset_at and time.time() >= reset_at:
                # Cooldown expired — mark as active again
                state["status"] = "active"
                orch.notifier.notify(
                    "provider_recovered",
                    f"✅ Provider {name} rate limit cooldown expired — marked active",
                    severity="info",
                    details={"provider": name},
                )
                notifications_sent.append(f"recovered:{name}")

        # Check 3: High error rate
        error_rate = state.get("error_rate", 0)
        if error_rate > 0.3 and state.get("requests_total", 0) > 10:
            orch.notifier.notify(
                "provider_degraded",
                f"⚡ Provider {name} error rate is {error_rate*100:.0f}% — consider switching",
                severity="warning",
                details={"provider": name, "error_rate": error_rate},
            )
            notifications_sent.append(f"degraded:{name}")

    # Check 4: Active provider is exhausted — need to switch
    if active and active in providers:
        active_state = providers[active].get("state", {})
        active_creds = providers[active].get("credentials", {})
        if active_state.get("status") in ("exhausted", "rate_limit") or active_creds.get("active", 0) == 0:
            # Find next best provider
            best = orch.router.get_best_provider()
            if best and best["name"] != active:
                orch.notifier.notify(
                    "provider_switched",
                    f"🔀 Auto-switched from {active} to {best['name']} (previous provider unavailable)",
                    severity="warning",
                    details={
                        "from": active,
                        "to": best["name"],
                        "reason": active_state.get("status", "unknown"),
                    },
                )
                notifications_sent.append(f"switched:{active}->{best['name']}")

                # If falling back to local, ensure it's running
                if best.get("is_local"):
                    if not orch.local_llm.is_running:
                        orch.notifier.notify(
                            "local_fallback_activating",
                            "🖥️ Starting local LLM server for fallback...",
                            severity="info",
                        )
                        orch.local_llm.ensure_running()

    # Check 5: Ensure local LLM is running if it's the only option
    available_count = sum(
        1 for p in providers.values()
        if p["state"].get("is_available") and p["credentials"].get("active", 0) > 0
    )
    if available_count == 0 and orch.config.local_model_path:
        if not orch.local_llm.is_running:
            orch.notifier.notify(
                "local_fallback_activating",
                "🖥️ All cloud providers exhausted — starting local LLM fallback",
                severity="critical",
            )
            orch.local_llm.ensure_running()

    # Write status snapshot
    _write_status_snapshot(status)

    if notifications_sent:
        log.info(f"Check complete. Notifications: {notifications_sent}")
    else:
        log.debug(f"Check complete. All providers healthy. Active: {active}")

    return status


def _write_status_snapshot(status: dict):
    """Write a status snapshot for the dashboard to read."""
    hermes_home = get_hermes_home()
    snapshot_path = hermes_home / "provider-router" / "status_snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(status, indent=2, default=str))


def run_daemon(interval_seconds: int = 120):
    """Run the monitor in a loop."""
    log.info(f"Provider Router Monitor started (interval: {interval_seconds}s)")
    while True:
        try:
            run_check()
        except Exception as e:
            log.error(f"Monitor check failed: {e}")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Provider Router Monitor")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=120, help="Check interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.interval)
    else:
        run_check()
