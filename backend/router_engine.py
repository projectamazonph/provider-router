"""
Provider Router — Intelligent token monitoring, provider rotation, and local LLM fallback.

This module provides:
1. TokenUsageMonitor — tracks per-provider token usage, costs, rate limits
2. ProviderRouter — intelligent provider selection and failover
3. NotificationManager — user notifications via in-chat and file logs
4. LocalLLMManager — manages the local llama.cpp fallback server
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Try to import hermes constants
try:
    from hermes_constants import get_hermes_home
except ImportError:
    def get_hermes_home() -> Path:
        val = (os.environ.get("HERMES_HOME") or "").strip()
        return Path(val) if val else Path.home() / ".hermes"


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────

class ProviderStatus(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    EXHAUSTED = "exhausted"
    ERROR = "error"
    OFFLINE = "offline"


class RotationStrategy(Enum):
    COST_FIRST = "cost_first"       # Pick cheapest available
    RELIABILITY_FIRST = "reliability_first"  # Pick most reliable
    ROUND_ROBIN = "round_robin"     # Cycle through providers
    PRIORITY = "priority"           # Use priority order from config


@dataclass
class ProviderState:
    """Tracks the real-time state of a single provider."""
    name: str
    base_url: str
    model: str
    status: str = "active"
    priority: int = 0
    # Token tracking
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    # Cost tracking
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0
    total_cost: float = 0.0
    # Rate limit tracking
    requests_total: int = 0
    errors_429: int = 0
    errors_total: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None
    rate_limit_reset_at: Optional[float] = None
    # Timing
    last_used_at: Optional[float] = None
    avg_latency_ms: float = 0.0
    # Credential info
    credential_count: int = 1
    active_credential_index: int = 0

    @property
    def is_available(self) -> bool:
        if self.status in ("exhausted", "offline"):
            return False
        if self.status == "rate_limited" and self.rate_limit_reset_at:
            return time.time() >= self.rate_limit_reset_at
        return self.status == "active"

    @property
    def error_rate(self) -> float:
        if self.requests_total == 0:
            return 0.0
        return self.errors_total / self.requests_total

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_available"] = self.is_available
        d["error_rate"] = self.error_rate
        return d


@dataclass
class RouterConfig:
    """Configuration for the provider router."""
    # Rotation
    strategy: str = "priority"
    auto_switch: bool = True
    notify_on_switch: bool = True
    notify_on_exhaustion: bool = True
    # Thresholds
    rate_limit_cooldown_seconds: int = 60
    max_error_rate: float = 0.5
    # Local LLM
    local_model_path: str = ""
    local_model_name: str = "local/llama-3.2-3b-instruct"
    local_server_port: int = 8080
    local_server_host: str = "127.0.0.1"
    local_context_length: int = 4096
    local_gpu_layers: int = 0  # 0 = CPU only
    local_threads: int = 4
    # Providers (ordered by priority)
    providers: list[dict] = field(default_factory=list)
    # Notification
    log_file: str = ""
    notification_cooldown_seconds: int = 300  # Don't spam: 5 min between same-type notifications

    @classmethod
    def from_dict(cls, d: dict) -> "RouterConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# Token Usage Monitor
# ──────────────────────────────────────────────────────────────────────────────

class TokenUsageMonitor:
    """
    Monitors token usage per provider by reading Hermes cost snapshots
    and auth.json credential pool status.
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self.hermes_home = hermes_home or get_hermes_home()
        self._snapshots_dir = self.hermes_home / "cost-snapshots"
        self._auth_path = self.hermes_home / "auth.json"
        self._router_state_path = self.hermes_home / "provider-router" / "state.json"
        self._lock = threading.Lock()

    def get_provider_usage(self, provider: str) -> dict:
        """Get current usage stats for a provider from cost snapshots."""
        snapshot_file = self._snapshots_dir / f"{provider}.json"
        if not snapshot_file.exists():
            return {"used": 0, "limit": None, "snapshots": []}
        try:
            data = json.loads(snapshot_file.read_text())
            snapshots = data.get("snapshots", [])
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_usage = sum(
                s.get("used", 0) for s in snapshots if s.get("date") == today
            )
            return {
                "used": today_usage,
                "limit": data.get("limit"),
                "snapshots": snapshots[-7:],  # Last 7 days
            }
        except Exception as e:
            log.warning(f"Failed to read cost snapshot for {provider}: {e}")
            return {"used": 0, "limit": None, "snapshots": []}

    def get_credential_status(self, provider: str) -> dict:
        """Get credential pool status from auth.json."""
        if not self._auth_path.exists():
            return {"total": 0, "active": 0, "exhausted": 0, "credentials": []}
        try:
            auth = json.loads(self._auth_path.read_text())
            pool = auth.get("credential_pool", {}).get(provider, [])
            total = len(pool)
            exhausted = sum(
                1 for c in pool
                if c.get("last_status") == "exhausted"
            )
            active = total - exhausted
            return {
                "total": total,
                "active": active,
                "exhausted": exhausted,
                "credentials": [
                    {
                        "id": c.get("id"),
                        "status": c.get("last_status", "unknown"),
                        "last_error": c.get("last_error_code"),
                        "last_used": c.get("last_status_at"),
                    }
                    for c in pool
                ],
            }
        except Exception as e:
            log.warning(f"Failed to read auth.json for {provider}: {e}")
            return {"total": 0, "active": 0, "exhausted": 0, "credentials": []}

    def get_all_provider_status(self) -> dict[str, dict]:
        """Get combined status for all known providers."""
        result = {}
        if self._snapshots_dir.exists():
            for f in self._snapshots_dir.glob("*.json"):
                provider = f.stem
                usage = self.get_provider_usage(provider)
                creds = self.get_credential_status(provider)
                result[provider] = {
                    "usage": usage,
                    "credentials": creds,
                }
        return result

    def record_usage(self, provider: str, tokens_in: int, tokens_out: int, cost: float = 0.0):
        """Record token usage for a provider (called after each API call)."""
        with self._lock:
            state = self._load_router_state()
            if provider not in state.get("providers", {}):
                state.setdefault("providers", {})[provider] = {
                    "tokens_in": 0, "tokens_out": 0, "total_cost": 0.0, "requests": 0
                }
            p = state["providers"][provider]
            p["tokens_in"] = p.get("tokens_in", 0) + tokens_in
            p["tokens_out"] = p.get("tokens_out", 0) + tokens_out
            p["total_cost"] = p.get("total_cost", 0.0) + cost
            p["requests"] = p.get("requests", 0) + 1
            p["last_used_at"] = time.time()
            self._save_router_state(state)

    def _load_router_state(self) -> dict:
        if self._router_state_path.exists():
            try:
                return json.loads(self._router_state_path.read_text())
            except Exception:
                pass
        return {"providers": {}, "rotation_log": [], "notifications": []}

    def _save_router_state(self, state: dict):
        self._router_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._router_state_path.write_text(json.dumps(state, indent=2, default=str))


# ──────────────────────────────────────────────────────────────────────────────
# Provider Router
# ──────────────────────────────────────────────────────────────────────────────

class ProviderRouter:
    """
    Intelligent provider selection with automatic failover.
    
    Selection logic:
    1. Filter out unavailable providers (exhausted, rate-limited, offline)
    2. Apply rotation strategy (priority, cost-first, reliability-first, round-robin)
    3. Return the best provider + model to use
    4. If all cloud providers are exhausted, fall back to local LLM
    """

    def __init__(self, config: RouterConfig, monitor: TokenUsageMonitor):
        self.config = config
        self.monitor = monitor
        self._provider_states: dict[str, ProviderState] = {}
        self._last_rotation_index = 0
        self._init_provider_states()

    def _init_provider_states(self):
        """Initialize provider states from config."""
        for i, p in enumerate(self.config.providers):
            name = p["name"]
            self._provider_states[name] = ProviderState(
                name=name,
                base_url=p.get("base_url", ""),
                model=p.get("model", ""),
                priority=p.get("priority", i),
                cost_per_input_token=p.get("cost_per_input_token", 0.0),
                cost_per_output_token=p.get("cost_per_output_token", 0.0),
            )

    def get_best_provider(self) -> Optional[dict]:
        """
        Select the best available provider based on the configured strategy.
        Returns dict with provider config or None if nothing is available.
        """
        available = self._get_available_providers()
        if not available:
            # Fall back to local LLM
            if self.config.local_model_path:
                return {
                    "name": "local",
                    "base_url": f"http://{self.config.local_server_host}:{self.config.local_server_port}/v1",
                    "model": self.config.local_model_name,
                    "is_local": True,
                }
            return None

        strategy = RotationStrategy(self.config.strategy)

        if strategy == RotationStrategy.PRIORITY:
            # Sort by priority (lower number = higher priority)
            available.sort(key=lambda p: p.priority)
            best = available[0]

        elif strategy == RotationStrategy.COST_FIRST:
            # Pick cheapest that's available
            available.sort(key=lambda p: p.cost_per_input_token + p.cost_per_output_token)
            best = available[0]

        elif strategy == RotationStrategy.RELIABILITY_FIRST:
            # Pick lowest error rate
            available.sort(key=lambda p: p.error_rate)
            best = available[0]

        elif strategy == RotationStrategy.ROUND_ROBIN:
            idx = self._last_rotation_index % len(available)
            self._last_rotation_index = (self._last_rotation_index + 1) % len(available)
            best = available[idx]

        else:
            best = available[0]

        return {
            "name": best.name,
            "base_url": best.base_url,
            "model": best.model,
            "is_local": False,
        }

    def _get_available_providers(self) -> list[ProviderState]:
        """Get list of currently available providers."""
        available = []
        for name, state in self._provider_states.items():
            # Refresh status from monitor
            creds = self.monitor.get_credential_status(name)
            state.credential_count = creds["total"]
            state.active_credential_index = creds["active"]

            # Check if provider has any active credentials
            if creds["active"] > 0 and state.is_available:
                available.append(state)
            elif creds["total"] == 0:
                # No credentials configured — might be a new provider
                # Check if it's reachable
                if state.status not in ("exhausted", "offline"):
                    available.append(state)

        return available

    def report_success(self, provider: str, tokens_in: int = 0, tokens_out: int = 0,
                       latency_ms: float = 0.0, cost: float = 0.0):
        """Report a successful API call."""
        if provider in self._provider_states:
            state = self._provider_states[provider]
            state.tokens_in += tokens_in
            state.tokens_out += tokens_out
            state.total_cost += cost
            state.requests_total += 1
            state.last_used_at = time.time()
            if latency_ms > 0:
                # Rolling average
                n = state.requests_total
                state.avg_latency_ms = (state.avg_latency_ms * (n - 1) + latency_ms) / n

        self.monitor.record_usage(provider, tokens_in, tokens_out, cost)

    def report_error(self, provider: str, error_code: int = 0, error_message: str = ""):
        """Report an API error."""
        if provider in self._provider_states:
            state = self._provider_states[provider]
            state.errors_total += 1
            state.last_error = error_message[:200]
            state.last_error_at = time.time()

            if error_code == 429:
                state.errors_429 += 1
                state.status = "rate_limited"
                state.rate_limit_reset_at = (
                    time.time() + self.config.rate_limit_cooldown_seconds
                )
                log.warning(f"Provider {provider} rate limited. Cooldown: {self.config.rate_limit_cooldown_seconds}s")

            # Check if all credentials are exhausted
            creds = self.monitor.get_credential_status(provider)
            if creds["active"] == 0 and creds["total"] > 0:
                state.status = "exhausted"
                log.warning(f"Provider {provider} all credentials exhausted!")

    def get_status_summary(self) -> dict:
        """Get a full status summary of all providers."""
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": self.config.strategy,
            "providers": {},
            "active_provider": None,
            "local_available": bool(self.config.local_model_path),
        }

        for name, state in self._provider_states.items():
            usage = self.monitor.get_provider_usage(name)
            creds = self.monitor.get_credential_status(name)
            summary["providers"][name] = {
                "state": state.to_dict(),
                "usage": usage,
                "credentials": creds,
            }

        best = self.get_best_provider()
        if best:
            summary["active_provider"] = best["name"]

        return summary


# ──────────────────────────────────────────────────────────────────────────────
# Notification Manager
# ──────────────────────────────────────────────────────────────────────────────

class NotificationManager:
    """
    Handles user notifications for provider events.
    Writes to both in-chat messages and a log file.
    """

    def __init__(self, config: RouterConfig, hermes_home: Optional[Path] = None):
        self.config = config
        self.hermes_home = hermes_home or get_hermes_home()
        self._log_path = (
            Path(config.log_file) if config.log_file
            else self.hermes_home / "provider-router" / "notifications.log"
        )
        self._last_notification: dict[str, float] = {}  # type -> timestamp
        self._lock = threading.Lock()

    def notify(self, event_type: str, message: str, severity: str = "info",
               details: Optional[dict] = None):
        """
        Send a notification. Respects cooldown to avoid spam.
        
        Event types: provider_exhausted, provider_switched, provider_recovered,
                     rate_limit_hit, local_fallback_activated, error
        """
        with self._lock:
            now = time.time()
            cooldown = self.config.notification_cooldown_seconds

            last_sent = self._last_notification.get(event_type, 0)
            if now - last_sent < cooldown and severity != "critical":
                return  # Skip — cooldown active

            self._last_notification[event_type] = now

        notification = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "severity": severity,
            "message": message,
            "details": details or {},
        }

        # Write to log file
        self._write_to_log(notification)

        # Write to in-chat notification file (picked up by Hermes cron/agent)
        self._write_in_chat_notification(notification)

        log.info(f"[ProviderRouter] {event_type}: {message}")

    def _write_to_log(self, notification: dict):
        """Append notification to the log file."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a") as f:
                f.write(json.dumps(notification) + "\n")
        except Exception as e:
            log.error(f"Failed to write notification log: {e}")

    def _write_in_chat_notification(self, notification: dict):
        """
        Write a notification that can be picked up by Hermes.
        Uses a simple file-based approach — a cron job or agent can read this.
        """
        try:
            notif_dir = self.hermes_home / "provider-router" / "pending_notifications"
            notif_dir.mkdir(parents=True, exist_ok=True)
            notif_file = notif_dir / f"{int(time.time())}.json"
            notif_file.write_text(json.dumps(notification, indent=2))
        except Exception as e:
            log.error(f"Failed to write in-chat notification: {e}")

    def get_recent_notifications(self, limit: int = 50) -> list[dict]:
        """Get recent notifications from the log file."""
        if not self._log_path.exists():
            return []
        try:
            lines = self._log_path.read_text().strip().split("\n")
            notifications = []
            for line in lines[-limit:]:
                try:
                    notifications.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return notifications
        except Exception:
            return []

    def get_pending_notifications(self) -> list[dict]:
        """Get unread in-chat notifications."""
        notif_dir = self.hermes_home / "provider-router" / "pending_notifications"
        if not notif_dir.exists():
            return []
        notifications = []
        for f in sorted(notif_dir.glob("*.json")):
            try:
                notifications.append(json.loads(f.read_text()))
            except Exception:
                continue
        return notifications

    def clear_pending_notifications(self):
        """Clear all pending in-chat notifications."""
        notif_dir = self.hermes_home / "provider-router" / "pending_notifications"
        if notif_dir.exists():
            for f in notif_dir.glob("*.json"):
                f.unlink()


# ──────────────────────────────────────────────────────────────────────────────
# Local LLM Manager
# ──────────────────────────────────────────────────────────────────────────────

class LocalLLMManager:
    """
    Manages the local llama.cpp server as a fallback provider.
    Handles starting/stopping the server and checking health.
    """

    def __init__(self, config: RouterConfig):
        self.config = config
        self._server_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Check if the local server is running."""
        if self._server_process is None:
            return False
        return self._server_process.poll() is None

    @property
    def base_url(self) -> str:
        return f"http://{self.config.local_server_host}:{self.config.local_server_port}/v1"

    def health_check(self) -> bool:
        """Check if the local server is healthy."""
        try:
            import urllib.request
            url = f"http://{self.config.local_server_host}:{self.config.local_server_port}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start_server(self) -> bool:
        """Start the llama.cpp server."""
        with self._lock:
            if self.is_running:
                return True

            model_path = self.config.local_model_path
            if not model_path or not Path(model_path).exists():
                log.error(f"Local model not found: {model_path}")
                return False

            cmd = [
                "llama-server",
                "--host", self.config.local_server_host,
                "--port", str(self.config.local_server_port),
                "--model", model_path,
                "--ctx-size", str(self.config.local_context_length),
                "--threads", str(self.config.local_threads),
                "--n-gpu-layers", str(self.config.local_gpu_layers),
            ]

            try:
                self._server_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # Wait for server to be ready
                for _ in range(30):  # 30 seconds max
                    time.sleep(1)
                    if self.health_check():
                        log.info(f"Local LLM server started on {self.base_url}")
                        return True
                    if self._server_process.poll() is not None:
                        log.error("Local LLM server exited unexpectedly")
                        return False

                log.error("Local LLM server failed to start within 30s")
                return False

            except FileNotFoundError:
                log.error("llama-server not found. Install llama.cpp first.")
                return False
            except Exception as e:
                log.error(f"Failed to start local LLM server: {e}")
                return False

    def stop_server(self):
        """Stop the local server."""
        with self._lock:
            if self._server_process and self.is_running:
                self._server_process.terminate()
                try:
                    self._server_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._server_process.kill()
                self._server_process = None
                log.info("Local LLM server stopped")

    def ensure_running(self) -> bool:
        """Ensure the local server is running, start if needed."""
        if self.is_running and self.health_check():
            return True
        return self.start_server()


# ──────────────────────────────────────────────────────────────────────────────
# Main Router Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

class ProviderRouterOrchestrator:
    """
    Main orchestrator that ties together monitoring, routing, notifications,
    and local LLM management.
    """

    def __init__(self, config: Optional[RouterConfig] = None):
        self.hermes_home = get_hermes_home()
        self.config_path = self.hermes_home / "provider-router" / "config.json"

        if config:
            self.config = config
        elif self.config_path.exists():
            self.config = RouterConfig.from_dict(json.loads(self.config_path.read_text()))
        else:
            self.config = self._default_config()

        self.monitor = TokenUsageMonitor(self.hermes_home)
        self.router = ProviderRouter(self.config, self.monitor)
        self.notifier = NotificationManager(self.config, self.hermes_home)
        self.local_llm = LocalLLMManager(self.config)

    def _default_config(self) -> RouterConfig:
        """Build default config from existing Hermes auth.json."""
        providers = []
        auth_path = self.hermes_home / "auth.json"
        if auth_path.exists():
            try:
                auth = json.loads(auth_path.read_text())
                pool = auth.get("credential_pool", {})
                for name, creds in pool.items():
                    if creds:  # Only add providers with credentials
                        providers.append({
                            "name": name,
                            "base_url": creds[0].get("base_url", ""),
                            "model": "",
                            "priority": len(providers),
                            "cost_per_input_token": 0.0,
                            "cost_per_output_token": 0.0,
                        })
            except Exception:
                pass

        return RouterConfig(providers=providers)

    def save_config(self):
        """Persist config to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config.to_dict(), indent=2))

    def get_recommended_model(self) -> str:
        """
        Recommend the best local model for this device.
        Based on available RAM and CPU.
        """
        # Check available RAM
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        available_kb = int(line.split()[1])
                        available_gb = available_kb / (1024 * 1024)
                        break
                else:
                    available_gb = 4.0
        except Exception:
            available_gb = 4.0

        # Recommend based on available RAM
        if available_gb >= 6:
            return "Qwen2.5-7B-Instruct-Q4_K_M.gguf"  # Best quality that fits
        elif available_gb >= 4:
            return "Qwen2.5-3B-Instruct-Q4_K_M.gguf"  # Good balance
        elif available_gb >= 2.5:
            return "Llama-3.2-3B-Instruct-Q4_K_M.gguf"  # Solid all-rounder
        else:
            return "Phi-3.5-mini-instruct-Q4_K_M.gguf"  # Smallest capable model

    def get_status(self) -> dict:
        """Get full system status."""
        status = self.router.get_status_summary()
        status["config"] = self.config.to_dict()
        status["notifications"] = self.notifier.get_recent_notifications(20)
        status["local_server_running"] = self.local_llm.is_running
        status["local_server_url"] = self.local_llm.base_url
        status["recommended_model"] = self.get_recommended_model()
        return status
