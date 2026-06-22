"""
Provider Router — token monitoring, provider rotation, local LLM fallback.

Classes:
  TokenUsageMonitor  — per-provider token/cost/credential tracking
  ProviderRouter     — provider selection with 4 strategies
  NotificationManager — file + in-chat notifications with cooldown
  Orchestrator       — ties everything together
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    from hermes_constants import get_hermes_home
except ImportError:
    def get_hermes_home() -> Path:
        val = (os.environ.get("HERMES_HOME") or "").strip()
        return Path(val) if val else Path.home() / ".hermes"


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class ProviderState:
    name: str
    base_url: str
    model: str
    status: str = "active"
    priority: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_cost: float = 0.0
    requests_total: int = 0
    errors_429: int = 0
    errors_total: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None
    rate_limit_reset_at: Optional[float] = None
    last_used_at: Optional[float] = None
    avg_latency_ms: float = 0.0

    @property
    def is_available(self) -> bool:
        if self.status in ("exhausted", "offline"):
            return False
        if self.status == "rate_limited" and self.rate_limit_reset_at:
            return time.time() >= self.rate_limit_reset_at
        return self.status == "active"

    @property
    def error_rate(self) -> float:
        return self.errors_total / self.requests_total if self.requests_total else 0.0


@dataclass
class RouterConfig:
    strategy: str = "priority"
    auto_switch: bool = True
    notify_on_switch: bool = True
    notify_on_exhaustion: bool = True
    rate_limit_cooldown_seconds: int = 60
    local_model_path: str = ""
    local_model_name: str = "local/llama-3.2-3b-instruct"
    local_server_port: int = 8080
    local_server_host: str = "127.0.0.1"
    local_context_length: int = 4096
    local_threads: int = 4
    providers: list[dict] = field(default_factory=list)
    log_file: str = ""
    notification_cooldown_seconds: int = 300

    @classmethod
    def from_dict(cls, d: dict) -> "RouterConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ─── Token Usage Monitor ──────────────────────────────────────────────────────

class TokenUsageMonitor:
    def __init__(self, hermes_home: Optional[Path] = None):
        self.hermes_home = hermes_home or get_hermes_home()
        self._snapshots_dir = self.hermes_home / "cost-snapshots"
        self._auth_path = self.hermes_home / "auth.json"
        self._state_path = self.hermes_home / "provider-router" / "state.json"

    def get_provider_usage(self, provider: str) -> dict:
        f = self._snapshots_dir / f"{provider}.json"
        if not f.exists():
            return {"used": 0, "limit": None}
        try:
            data = json.loads(f.read_text())
            today = time.strftime("%Y-%m-%d", time.gmtime())
            used = sum(s.get("used", 0) for s in data.get("snapshots", []) if s.get("date") == today)
            return {"used": used, "limit": data.get("limit")}
        except Exception:
            return {"used": 0, "limit": None}

    def get_credential_status(self, provider: str) -> dict:
        if not self._auth_path.exists():
            return {"total": 0, "active": 0, "exhausted": 0}
        try:
            pool = json.loads(self._auth_path.read_text()).get("credential_pool", {}).get(provider, [])
            total = len(pool)
            exhausted = sum(1 for c in pool if c.get("last_status") == "exhausted")
            return {"total": total, "active": total - exhausted, "exhausted": exhausted}
        except Exception:
            return {"total": 0, "active": 0, "exhausted": 0}

    def record_usage(self, provider: str, tokens_in: int, tokens_out: int, cost: float = 0.0):
        try:
            state = json.loads(self._state_path.read_text()) if self._state_path.exists() else {}
        except Exception:
            state = {}
        p = state.setdefault(provider, {"tokens_in": 0, "tokens_out": 0, "total_cost": 0.0, "requests": 0})
        p["tokens_in"] += tokens_in
        p["tokens_out"] += tokens_out
        p["total_cost"] += cost
        p["requests"] += 1
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2))


# ─── Provider Router ──────────────────────────────────────────────────────────

class ProviderRouter:
    def __init__(self, config: RouterConfig, monitor: TokenUsageMonitor):
        self.config = config
        self.monitor = monitor
        self._states: dict[str, ProviderState] = {}
        self._rr_index = 0
        for i, p in enumerate(config.providers):
            self._states[p["name"]] = ProviderState(
                name=p["name"], base_url=p.get("base_url", ""),
                model=p.get("model", ""), priority=p.get("priority", i),
            )

    def get_best_provider(self) -> Optional[dict]:
        available = self._available()
        if not available:
            if self.config.local_model_path:
                return {"name": "local", "base_url": f"http://{self.config.local_server_host}:{self.config.local_server_port}/v1",
                        "model": self.config.local_model_name, "is_local": True}
            return None

        strategy = self.config.strategy
        if strategy == "cost_first":
            available.sort(key=lambda p: p.total_cost)
        elif strategy == "reliability_first":
            available.sort(key=lambda p: p.error_rate)
        elif strategy == "round_robin":
            self._rr_index = (self._rr_index + 1) % len(available)
            return {"name": available[self._rr_index].name, "base_url": available[self._rr_index].base_url,
                    "model": available[self._rr_index].model, "is_local": False}
        # priority (default) — already ordered by config
        return {"name": available[0].name, "base_url": available[0].base_url,
                "model": available[0].model, "is_local": False}

    def _available(self) -> list[ProviderState]:
        out = []
        for name, state in self._states.items():
            creds = self.monitor.get_credential_status(name)
            if creds["active"] > 0 and state.is_available:
                out.append(state)
            elif creds["total"] == 0 and state.status not in ("exhausted", "offline"):
                out.append(state)
        return out

    def report_success(self, provider: str, tokens_in: int = 0, tokens_out: int = 0,
                       latency_ms: float = 0.0, cost: float = 0.0):
        if provider in self._states:
            s = self._states[provider]
            s.tokens_in += tokens_in
            s.tokens_out += tokens_out
            s.total_cost += cost
            s.requests_total += 1
            s.last_used_at = time.time()
            if latency_ms > 0 and s.requests_total > 0:
                s.avg_latency_ms = (s.avg_latency_ms * (s.requests_total - 1) + latency_ms) / s.requests_total
        self.monitor.record_usage(provider, tokens_in, tokens_out, cost)

    def report_error(self, provider: str, error_code: int = 0, error_message: str = ""):
        if provider in self._states:
            s = self._states[provider]
            s.errors_total += 1
            s.last_error = error_message[:200]
            s.last_error_at = time.time()
            if error_code == 429:
                s.errors_429 += 1
                s.status = "rate_limited"
                s.rate_limit_reset_at = time.time() + self.config.rate_limit_cooldown_seconds
            if self.monitor.get_credential_status(provider)["active"] == 0:
                s.status = "exhausted"

    def get_status_summary(self) -> dict:
        summary = {"strategy": self.config.strategy, "providers": {}, "active_provider": None,
                   "local_available": bool(self.config.local_model_path)}
        for name, state in self._states.items():
            summary["providers"][name] = {
                "state": {**state.__dict__, "is_available": state.is_available, "error_rate": state.error_rate},
                "usage": self.monitor.get_provider_usage(name),
                "credentials": self.monitor.get_credential_status(name),
            }
        best = self.get_best_provider()
        if best:
            summary["active_provider"] = best["name"]
        return summary


# ─── Notification Manager ─────────────────────────────────────────────────────

class NotificationManager:
    def __init__(self, config: RouterConfig, hermes_home: Optional[Path] = None):
        self.config = config
        self._log_path = Path(config.log_file) if config.log_file else (hermes_home or get_hermes_home()) / "provider-router" / "notifications.log"
        self._last: dict[str, float] = {}

    def notify(self, event_type: str, message: str, severity: str = "info", details: Optional[dict] = None):
        now = time.time()
        if now - self._last.get(event_type, 0) < self.config.notification_cooldown_seconds and severity != "critical":
            return
        self._last[event_type] = now
        entry = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "type": event_type,
                 "severity": severity, "message": message, "details": details or {}}
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.error("Failed to write notification: %s", e)
        log.info("[ProviderRouter] %s: %s", event_type, message)

    def get_recent_notifications(self, limit: int = 50) -> list[dict]:
        if not self._log_path.exists():
            return []
        try:
            lines = self._log_path.read_text().strip().split("\n")
            return [json.loads(l) for l in lines[-limit:] if l]
        except Exception:
            return []


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class ProviderRouterOrchestrator:
    def __init__(self, config: Optional[RouterConfig] = None):
        self.hermes_home = get_hermes_home()
        if config:
            self.config = config
        elif (self.hermes_home / "provider-router" / "config.json").exists():
            self.config = RouterConfig.from_dict(json.loads((self.hermes_home / "provider-router" / "config.json").read_text()))
        else:
            self.config = self._default_config()
        self.monitor = TokenUsageMonitor(self.hermes_home)
        self.router = ProviderRouter(self.config, self.monitor)
        self.notifier = NotificationManager(self.config, self.hermes_home)

    def _default_config(self) -> RouterConfig:
        providers = []
        auth_path = self.hermes_home / "auth.json"
        if auth_path.exists():
            try:
                pool = json.loads(auth_path.read_text()).get("credential_pool", {})
                for i, (name, creds) in enumerate(pool.items()):
                    if creds:
                        providers.append({"name": name, "base_url": creds[0].get("base_url", ""),
                                          "model": "", "priority": i})
            except Exception:
                pass
        return RouterConfig(providers=providers)

    def save_config(self):
        path = self.hermes_home / "provider-router" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.config.to_dict(), indent=2))

    def get_recommended_model(self) -> str:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        avail_gb = int(line.split()[1]) / (1024 * 1024)
                        break
                else:
                    avail_gb = 4.0
        except Exception:
            avail_gb = 4.0
        if avail_gb >= 6: return "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
        if avail_gb >= 4: return "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
        return "Llama-3.2-3B-Instruct-Q4_K_M.gguf"

    def get_status(self) -> dict:
        s = self.router.get_status_summary()
        s["config"] = self.config.to_dict()
        s["notifications"] = self.notifier.get_recent_notifications(20)
        s["local_server_running"] = False
        s["local_server_url"] = f"http://{self.config.local_server_host}:{self.config.local_server_port}/v1"
        s["recommended_model"] = self.get_recommended_model()
        return s
