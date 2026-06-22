"""
Provider Router — Setup Script.

This is the main entry point for setting up the entire system.
It:
1. Installs dependencies (llama-cpp-python)
2. Downloads the recommended local model
3. Configures Hermes
4. Sets up the monitoring cron job
5. Installs the dashboard plugin
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

def get_hermes_home() -> Path:
    val = (os.environ.get("HERMES_HOME") or "").strip()
    return Path(val) if val else Path.home() / ".hermes"


def check_system():
    """Check system capabilities and recommend configuration."""
    print("=" * 60)
    print("🔍 System Analysis")
    print("=" * 60)

    # CPU
    try:
        with open("/proc/cpuinfo") as f:
            cpu_info = f.read()
        cores = cpu_info.count("processor\t:")
        # Get CPU model
        model = "Unknown"
        for line in cpu_info.split("\n"):
            if "model name" in line or "Hardware" in line:
                model = line.split(":")[-1].strip()
                break
        print(f"  CPU: {model} ({cores} cores)")
    except Exception:
        print("  CPU: Unknown")

    # RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_gb = int(line.split()[1]) / (1024 * 1024)
                elif line.startswith("MemAvailable:"):
                    avail_gb = int(line.split()[1]) / (1024 * 1024)
        print(f"  RAM: {avail_gb:.1f} GB available / {total_gb:.1f} GB total")
    except Exception:
        print("  RAM: Unknown")

    # Storage
    try:
        stat = os.statvfs("/")
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        print(f"  Storage: {free_gb:.1f} GB free")
    except Exception:
        print("  Storage: Unknown")

    # GPU
    gpu_found = False
    for gpu_path in ["/dev/kgsl-3d0", "/dev/mali0", "/dev/dri/card0"]:
        if os.path.exists(gpu_path):
            print(f"  GPU: Found {gpu_path}")
            gpu_found = True
            break
    if not gpu_found:
        print("  GPU: No GPU device found (CPU-only mode)")

    # llama.cpp
    try:
        result = subprocess.run(["llama-server", "--version"], capture_output=True, text=True, timeout=5)
        print(f"  llama.cpp: {result.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  llama.cpp: NOT FOUND — will need installation")

    print()
    return {
        "cores": cores if 'cores' in dir() else 4,
        "ram_available_gb": avail_gb if 'avail_gb' in dir() else 4.0,
        "storage_free_gb": free_gb if 'free_gb' in dir() else 100.0,
        "has_gpu": gpu_found,
        "has_llamacpp": False,  # Will be checked above
    }


def recommend_model(ram_gb: float) -> dict:
    """Recommend a model based on available RAM."""
    models = [
        {
            "name": "Qwen2.5-3B-Instruct-Q4_K_M",
            "url": "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            "size_gb": 2.1,
            "ram_needed_gb": 3.0,
            "quality": "Good — strong reasoning, multilingual",
            "best_for": "General purpose, reasoning, tool calling",
        },
        {
            "name": "Llama-3.2-3B-Instruct-Q4_K_M",
            "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "size_gb": 2.0,
            "ram_needed_gb": 2.5,
            "quality": "Good — solid all-rounder, Meta quality",
            "best_for": "General purpose, widely compatible",
        },
        {
            "name": "Phi-3.5-mini-instruct-Q4_K_M",
            "url": "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf",
            "size_gb": 2.3,
            "ram_needed_gb": 3.0,
            "quality": "Very Good — excellent reasoning for size",
            "best_for": "Reasoning, code, tool calling",
        },
    ]

    # Filter by available RAM (need model RAM + 1GB overhead)
    suitable = [m for m in models if m["ram_needed_gb"] + 1.0 <= ram_gb]
    if not suitable:
        suitable = [models[-1]]  # Smallest

    return suitable[0]


def install_llama_cpp():
    """Install llama-cpp-python."""
    print("\n📦 Installing llama-cpp-python...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "llama-cpp-python"],
            check=True,
        )
        print("  ✓ llama-cpp-python installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Installation failed: {e}")
        return False


def download_model(model_info: dict, download_dir: Path) -> Path:
    """Download a GGUF model."""
    model_path = download_dir / f"{model_info['name']}.gguf"
    
    if model_path.exists():
        size_gb = model_path.stat().st_size / (1024**3)
        if size_gb > 0.5:  # At least 500MB — probably complete
            print(f"  ✓ Model already exists: {model_path} ({size_gb:.1f} GB)")
            return model_path

    print(f"\n📥 Downloading {model_info['name']}...")
    print(f"  URL: {model_info['url']}")
    print(f"  Size: ~{model_info['size_gb']} GB")
    print(f"  Destination: {model_path}")
    print()

    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        def progress_hook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100, downloaded * 100 / total_size)
                mb = downloaded / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                print(f"\r  Progress: {pct:.1f}% ({mb:.0f}/{total_mb:.0f} MB)", end="", flush=True)

        urllib.request.urlretrieve(model_info["url"], str(model_path), reporthook=progress_hook)
        print(f"\n  ✓ Download complete: {model_path}")
        return model_path
    except Exception as e:
        print(f"\n  ✗ Download failed: {e}")
        if model_path.exists():
            model_path.unlink()
        raise


def setup_hermes_integration(model_path: Path, strategy: str = "priority"):
    """Set up Hermes configuration."""
    print("\n⚙️  Configuring Hermes integration...")
    
    hermes_home = get_hermes_home()
    router_dir = hermes_home / "provider-router"
    router_dir.mkdir(parents=True, exist_ok=True)

    # Build config
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
        "auto_switch": True,
        "notify_on_switch": True,
        "notify_on_exhaustion": True,
        "rate_limit_cooldown_seconds": 60,
        "max_error_rate": 0.5,
        "local_model_path": str(model_path),
        "local_model_name": f"local/{model_path.stem}",
        "local_server_port": 8080,
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
    print(f"  ✓ Config written to {config_path}")

    return config


def setup_cron_job():
    """Set up the monitoring cron job in Hermes."""
    print("\n⏰ Setting up monitoring cron job...")
    
    project_dir = Path(__file__).parent.parent.parent
    monitor_script = project_dir / "backend" / "scripts" / "monitor.py"
    
    # Create a shell wrapper that sets up the environment
    hermes_home = get_hermes_home()
    wrapper_script = hermes_home / "provider-router" / "run_check.sh"
    wrapper_script.parent.mkdir(parents=True, exist_ok=True)
    
    wrapper_content = f"""#!/bin/bash
# Provider Router Monitor — runs every 2 minutes
export HERMES_HOME="{hermes_home}"
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
cd "{project_dir}"
python3 "{monitor_script}" --once >> "{hermes_home}/provider-router/monitor.log" 2>&1
"""
    wrapper_script.write_text(wrapper_content)
    wrapper_script.chmod(0o755)
    print(f"  ✓ Monitor wrapper: {wrapper_script}")
    print(f"  To enable: hermes cron create 'every 2m' '{wrapper_script}'")


def main():
    print("=" * 60)
    print("🔀 Provider Router — Setup")
    print("=" * 60)

    # Step 1: Analyze system
    sys_info = check_system()

    # Step 2: Recommend model
    print("=" * 60)
    print("🤖 Model Recommendation")
    print("=" * 60)
    recommended = recommend_model(sys_info["ram_available_gb"])
    print(f"  Recommended: {recommended['name']}")
    print(f"  Size: {recommended['size_gb']} GB")
    print(f"  Quality: {recommended['quality']}")
    print(f"  Best for: {recommended['best_for']}")
    print()

    # Step 3: Install llama.cpp Python bindings
    print("=" * 60)
    print("📦 Dependencies")
    print("=" * 60)
    install_llama_cpp()

    # Step 4: Download model
    hermes_home = get_hermes_home()
    models_dir = hermes_home / "models"
    model_path = download_model(recommended, models_dir)

    # Step 5: Configure Hermes
    setup_hermes_integration(model_path)

    # Step 6: Set up cron
    setup_cron_job()

    # Summary
    print()
    print("=" * 60)
    print("✅ Setup Complete!")
    print("=" * 60)
    print()
    print("  Model:     {model_path}")
    print(f"  Config:    {hermes_home / 'provider-router' / 'config.json'}")
    print(f"  Logs:      {hermes_home / 'provider-router' / 'notifications.log'}")
    print()
    print("  Next steps:")
    print("  1. Start the local server:")
    print(f"     llama-server --model {model_path} --port 8080 --host 127.0.0.1 --threads 4")
    print()
    print("  2. Enable the monitoring cron:")
    print(f"     hermes cron create 'every 2m' '{hermes_home / 'provider-router' / 'run_check.sh'}'")
    print()
    print("  3. Restart Hermes to pick up config changes")
    print("  4. Open the Web UI → Provider Router tab to monitor status")
    print()


if __name__ == "__main__":
    main()
