"""
Provider Router — Dashboard Plugin Backend API.

Mounted at /api/plugins/provider-router/ by the Hermes dashboard plugin system.
Provides REST endpoints for:
- Provider status dashboard
- Configuration management
- Rotation logs and notifications
- Local LLM management
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Add project to path for imports
import os
PROJECT_DIR = Path("/root/hermes/workspace/projects/provider-router")
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Also add hermes home for router_engine imports
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

try:
    from fastapi import APIRouter, HTTPException, Query
    from fastapi.responses import JSONResponse
except Exception:
    # Stub for testing without FastAPI
    class APIRouter:
        def get(self, *a, **kw): return lambda fn: fn
        def post(self, *a, **kw): return lambda fn: fn
        def put(self, *a, **kw): return lambda fn: fn
        def delete(self, *a, **kw): return lambda fn: fn

from backend.router_engine import (
    ProviderRouterOrchestrator,
    RouterConfig,
    TokenUsageMonitor,
)

log = logging.getLogger(__name__)
router = APIRouter()

# Global orchestrator instance
_orchestrator: Optional[ProviderRouterOrchestrator] = None


def get_orchestrator() -> ProviderRouterOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ProviderRouterOrchestrator()
    return _orchestrator


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard Status
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status():
    """Get full provider router status for the dashboard."""
    try:
        orch = get_orchestrator()
        return orch.get_status()
    except Exception as e:
        log.error(f"Error getting status: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@router.get("/providers")
def get_providers():
    """Get list of all providers and their current status."""
    try:
        orch = get_orchestrator()
        return orch.router.get_status_summary()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/providers/{provider_name}")
def get_provider_detail(provider_name: str):
    """Get detailed status for a specific provider."""
    try:
        orch = get_orchestrator()
        summary = orch.router.get_status_summary()
        if provider_name not in summary.get("providers", {}):
            raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")
        return summary["providers"][provider_name]
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/config")
def get_config():
    """Get current router configuration."""
    try:
        orch = get_orchestrator()
        return orch.config.to_dict()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/config")
def update_config(config: dict):
    """Update router configuration."""
    try:
        orch = get_orchestrator()
        new_config = RouterConfig.from_dict(config)
        orch.config = new_config
        orch.save_config()
        # Reinitialize router with new config
        orch.router = ProviderRouterOrchestrator(new_config).router
        return {"status": "ok", "config": orch.config.to_dict()}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.post("/config/provider")
def add_provider(provider: dict):
    """Add a new provider to the rotation."""
    try:
        orch = get_orchestrator()
        orch.config.providers.append(provider)
        orch.save_config()
        return {"status": "ok", "providers": orch.config.providers}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.delete("/config/provider/{provider_name}")
def remove_provider(provider_name: str):
    """Remove a provider from rotation."""
    try:
        orch = get_orchestrator()
        orch.config.providers = [
            p for p in orch.config.providers if p.get("name") != provider_name
        ]
        orch.save_config()
        return {"status": "ok", "providers": orch.config.providers}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ──────────────────────────────────────────────────────────────────────────────
# Notifications & Logs
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/notifications")
def get_notifications(limit: int = Query(50, ge=1, le=200)):
    """Get recent notifications."""
    try:
        orch = get_orchestrator()
        return orch.notifier.get_recent_notifications(limit)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/notifications/pending")
def get_pending_notifications():
    """Get pending (unread) in-chat notifications."""
    try:
        orch = get_orchestrator()
        return orch.notifier.get_pending_notifications()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/notifications/clear")
def clear_notifications():
    """Clear all pending notifications."""
    try:
        orch = get_orchestrator()
        orch.notifier.clear_pending_notifications()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/logs")
def get_rotation_logs(limit: int = Query(100, ge=1, le=500)):
    """Get rotation event logs."""
    try:
        state_path = (
            Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
            / "provider-router" / "state.json"
        )
        if not state_path.exists():
            return []
        state = json.loads(state_path.read_text())
        return state.get("rotation_log", [])[-limit:]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────────────────────────────────────
# Local LLM Management
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/local/status")
def get_local_status():
    """Get local LLM server status."""
    try:
        orch = get_orchestrator()
        return {
            "running": orch.local_llm.is_running,
            "healthy": orch.local_llm.health_check(),
            "url": orch.local_llm.base_url,
            "model_path": orch.config.local_model_path,
            "model_name": orch.config.local_model_name,
            "recommended_model": orch.get_recommended_model(),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/local/start")
def start_local_server():
    """Start the local LLM server."""
    try:
        orch = get_orchestrator()
        success = orch.local_llm.start_server()
        return {
            "status": "started" if success else "failed",
            "running": orch.local_llm.is_running,
            "url": orch.local_llm.base_url,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/local/stop")
def stop_local_server():
    """Stop the local LLM server."""
    try:
        orch = get_orchestrator()
        orch.local_llm.stop_server()
        return {"status": "stopped", "running": False}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────────────────────────────────────
# Manual Controls
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/rotate")
def force_rotate():
    """Force rotation to the next available provider."""
    try:
        orch = get_orchestrator()
        best = orch.router.get_best_provider()
        if best:
            orch.notifier.notify(
                "provider_switched",
                f"Manually rotated to provider: {best['name']}",
                severity="info",
                details=best,
            )
        return {"status": "ok", "active_provider": best}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/report-error")
def report_error(data: dict):
    """Report an error for a provider (called by hooks)."""
    try:
        orch = get_orchestrator()
        provider = data.get("provider", "")
        error_code = data.get("error_code", 0)
        error_message = data.get("error_message", "")

        orch.router.report_error(provider, error_code, error_message)

        if error_code == 429:
            orch.notifier.notify(
                "rate_limit_hit",
                f"Provider {provider} rate limited (429)",
                severity="warning",
                details={"provider": provider, "error_code": error_code},
            )
        elif error_code == 401:
            orch.notifier.notify(
                "provider_error",
                f"Provider {provider} authentication failed (401)",
                severity="critical",
                details={"provider": provider, "error_code": error_code},
            )

        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/report-success")
def report_success(data: dict):
    """Report a successful API call (called by hooks)."""
    try:
        orch = get_orchestrator()
        provider = data.get("provider", "")
        tokens_in = data.get("tokens_in", 0)
        tokens_out = data.get("tokens_out", 0)
        latency_ms = data.get("latency_ms", 0)
        cost = data.get("cost", 0.0)

        orch.router.report_success(provider, tokens_in, tokens_out, latency_ms, cost)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
