"""
Hermes Config Integration for Provider Router.

This script integrates the provider router into Hermes by:
1. Adding the local LLM as a provider in config.yaml
2. Setting up fallback_providers
3. Configuring credential_pool_strategies
4. Installing the dashboard plugin
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Config Integration
# ──────────────────────────────────────────────────────────────────────────────

def get_hermes_home() -> Path:
    val = (os.environ.get("HERMES_HOME") or "").strip()
    return Path(val) if val else Path.home() / ".hermes"


def integrate_with_hermes(
    local_model_path: str = "",
    local_port: int = 8080,
    strategy: str = "priority",
    auto_switch: bool = True,
):
    """
    Integrate the provider router into Hermes configuration.
    
    This:
    1. Creates/updates ~/.hermes/provider-router/config.json
    2. Updates ~/.hermes/config.yaml with fallback_providers
    3. Installs the dashboard plugin
    """
    hermes_home = get_hermes_home()
    router_dir = hermes_home / "provider-router"
    router_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build router config from current auth.json
    auth_path = hermes_home / "auth.json"
    providers = []
    if auth_path.exists():
        auth = json.loads(auth_path.read_text())
        pool = auth.get("credential_pool", {})
        for i, (name, creds) in enumerate(pool.items()):
            if creds:
                providers.append({
                    "name": name,
                    "base_url": creds[0].get("base_url", ""),
                    "model": "",
                    "priority": i,
                    "cost_per_input_token": 0.0,
                    "cost_per_output_token": 0.0,
                })

    config = {
        "strategy": strategy,
        "auto_switch": auto_switch,
        "notify_on_switch": True,
        "notify_on_exhaustion": True,
        "rate_limit_cooldown_seconds": 60,
        "max_error_rate": 0.5,
        "local_model_path": local_model_path,
        "local_model_name": "local/llama-3.2-3b-instruct",
        "local_server_port": local_port,
        "local_server_host": "127.0.0.1",
        "local_context_length": 4096,
        "local_gpu_layers": 0,
        "local_threads": 4,
        "providers": providers,
        "log_file": str(router_dir / "notifications.log"),
        "notification_cooldown_seconds": 300,
    }

    config_path = router_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    print(f"✓ Router config written to {config_path}")

    # 2. Update Hermes config.yaml
    config_yaml_path = hermes_home / "config.yaml"
    if config_yaml_path.exists():
        import yaml
        with open(config_yaml_path) as f:
            hermes_config = yaml.safe_load(f) or {}

        # Add fallback providers
        fallback_providers = hermes_config.get("fallback_providers", [])
        local_fallback = {
            "provider": "custom",
            "base_url": f"http://127.0.0.1:{local_port}/v1",
            "default": "local/llama-3.2-3b-instruct",
        }
        # Don't duplicate
        if not any(
            f.get("base_url") == local_fallback["base_url"]
            for f in fallback_providers
        ):
            fallback_providers.append(local_fallback)
            hermes_config["fallback_providers"] = fallback_providers

        # Enable credential pool strategies
        credential_strategies = hermes_config.get("credential_pool_strategies", {})
        if not credential_strategies:
            hermes_config["credential_pool_strategies"] = {
                "openrouter": {"strategy": "failover"},
                "nvidia": {"strategy": "failover"},
                "gemini": {"strategy": "failover"},
            }

        with open(config_yaml_path, "w") as f:
            yaml.dump(hermes_config, f, default_flow_style=False, sort_keys=False)
        print(f"✓ Hermes config.yaml updated with fallback providers")

    # 3. Install dashboard plugin
    _install_dashboard_plugin()

    print("\n✓ Provider Router integration complete!")
    print(f"  Config: {config_path}")
    print(f"  Logs:   {router_dir / 'notifications.log'}")
    print(f"\nNext steps:")
    print(f"  1. Download a GGUF model to use as local fallback")
    print(f"  2. Update local_model_path in {config_path}")
    print(f"  3. Start the local server: python -m backend.scripts.start_local")
    print(f"  4. Restart Hermes to pick up config changes")


def _install_dashboard_plugin():
    """Install the dashboard plugin for the Web UI."""
    hermes_home = get_hermes_home()
    plugin_dir = hermes_home / "provider-router" / "dashboard-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # Write plugin manifest
    manifest = {
        "name": "provider-router",
        "displayName": "Provider Router",
        "description": "Monitor token usage, manage provider rotation, and control local LLM fallback",
        "version": "1.0.0",
        "entry": "index.js",
        "icon": "router",
        "category": "infrastructure",
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"✓ Dashboard plugin manifest written to {plugin_dir / 'manifest.json'}")


def remove_integration():
    """Remove provider router integration from Hermes."""
    hermes_home = get_hermes_home()
    router_dir = hermes_home / "provider-router"

    if router_dir.exists():
        import shutil
        shutil.rmtree(router_dir)
        print(f"✓ Removed {router_dir}")

    # Clean config.yaml
    config_yaml_path = hermes_home / "config.yaml"
    if config_yaml_path.exists():
        import yaml
        with open(config_yaml_path) as f:
            hermes_config = yaml.safe_load(f) or {}

        # Remove local fallback
        fallback_providers = hermes_config.get("fallback_providers", [])
        hermes_config["fallback_providers"] = [
            f for f in fallback_providers
            if "127.0.0.1" not in f.get("base_url", "")
        ]

        with open(config_yaml_path, "w") as f:
            yaml.dump(hermes_config, f, default_flow_style=False, sort_keys=False)
        print("✓ Cleaned config.yaml")

    print("✓ Provider Router integration removed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Provider Router Hermes Integration")
    parser.add_argument("--install", action="store_true", help="Install integration")
    parser.add_argument("--remove", action="store_true", help="Remove integration")
    parser.add_argument("--model-path", default="", help="Path to local GGUF model")
    parser.add_argument("--port", type=int, default=8080, help="Local server port")
    parser.add_argument("--strategy", default="priority", help="Rotation strategy")
    args = parser.parse_args()

    if args.remove:
        remove_integration()
    else:
        integrate_with_hermes(
            local_model_path=args.model_path,
            local_port=args.port,
            strategy=args.strategy,
        )
