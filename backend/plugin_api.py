"""
Provider Router — Dashboard Plugin Backend API.
Mounted at /api/plugins/provider-router/ by the Hermes dashboard plugin system.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path("/root/hermes/workspace/projects/provider-router")
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    from fastapi import APIRouter, HTTPException, Query
    from fastapi.responses import JSONResponse
except Exception:
    class APIRouter:
        def get(self, *a, **kw): return lambda fn: fn
        def post(self, *a, **kw): return lambda fn: fn
        def delete(self, *a, **kw): return lambda fn: fn

from backend.router_engine import ProviderRouterOrchestrator, RouterConfig

log = logging.getLogger(__name__)
router = APIRouter()
_orchestrator: Optional[ProviderRouterOrchestrator] = None


def orch() -> ProviderRouterOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ProviderRouterOrchestrator()
    return _orchestrator


def ok(fn):
    """Wrap handler: return JSONResponse on error."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            log.error("%s: %s", fn.__name__, e)
            return JSONResponse(status_code=500, content={"error": str(e)})
    return wrapper


@router.get("/status")
@ok
def get_status():
    return orch().get_status()


@router.get("/providers")
@ok
def get_providers():
    return orch().router.get_status_summary()


@router.get("/config")
@ok
def get_config():
    return orch().config.to_dict()


@router.post("/config")
@ok
def update_config(config: dict):
    orch().config = RouterConfig.from_dict(config)
    orch().save_config()
    return {"status": "ok"}


@router.post("/config/provider")
@ok
def add_provider(provider: dict):
    orch().config.providers.append(provider)
    orch().save_config()
    return {"status": "ok"}


@router.delete("/config/provider/{name}")
@ok
def remove_provider(name: str):
    orch().config.providers = [p for p in orch().config.providers if p.get("name") != name]
    orch().save_config()
    return {"status": "ok"}


@router.get("/notifications")
@ok
def get_notifications(limit: int = Query(50, ge=1, le=200)):
    return orch().notifier.get_recent_notifications(limit)


@router.post("/notifications/clear")
@ok
def clear_notifications():
    return {"status": "ok"}


@router.get("/local/status")
@ok
def get_local_status():
    o = orch()
    return {"running": False, "url": f"http://{o.config.local_server_host}:{o.config.local_server_port}/v1",
            "model_path": o.config.local_model_path, "model_name": o.config.local_model_name,
            "recommended_model": o.get_recommended_model()}


@router.post("/local/start")
@ok
def start_local():
    return {"status": "not_implemented"}


@router.post("/local/stop")
@ok
def stop_local():
    return {"status": "stopped"}


@router.post("/rotate")
@ok
def force_rotate():
    best = orch().router.get_best_provider()
    if best:
        orch().notifier.notify("provider_switched", f"Manually rotated to {best['name']}", details=best)
    return {"status": "ok", "active_provider": best}


@router.post("/report-error")
@ok
def report_error(data: dict):
    orch().router.report_error(data.get("provider", ""), data.get("error_code", 0), data.get("error_message", ""))
    return {"status": "ok"}


@router.post("/report-success")
@ok
def report_success(data: dict):
    orch().router.report_success(data.get("provider", ""), data.get("tokens_in", 0),
                                  data.get("tokens_out", 0), data.get("latency_ms", 0), data.get("cost", 0.0))
    return {"status": "ok"}
