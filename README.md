# 🔀 Provider Router

Intelligent token monitoring, provider rotation, and local LLM fallback for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

## What It Does

- **Monitors** token usage, costs, and rate limits across all your LLM providers
- **Auto-switches** to the best available provider when one hits its limit
- **Falls back** to a local LLM (llama.cpp) when all cloud providers are exhausted
- **Notifies** you of events (exhaustion, switches, recoveries) via in-chat messages and log files
- **Dashboard tab** in the Hermes Web UI with real-time status, settings, and logs

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Hermes Agent                          │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  TokenUsage   │  │   Provider   │  │ Notification │  │
│  │  Monitor      │  │   Router     │  │ Manager      │  │
│  │              │  │              │  │              │  │
│  │ • Cost snaps │  │ • Priority   │  │ • Log file   │  │
│  │ • Auth pool  │  │ • Cost-first │  │ • In-chat    │  │
│  │ • Per-provider│  │ • Reliability│  │ • Cooldown   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │          │
│         └────────┬────────┴──────────────────┘          │
│                  │                                       │
│         ┌────────▼────────┐                             │
│         │  Orchestrator   │                             │
│         └────────┬────────┘                             │
│                  │                                       │
│    ┌─────────────┼─────────────┐                        │
│    │             │             │                        │
│  ┌─▼──┐    ┌────▼────┐  ┌────▼────┐                    │
│  │Cron│    │Dashboard│  │  Local  │                    │
│  │Job │    │ Plugin  │  │  LLM    │                    │
│  └────┘    └─────────┘  └─────────┘                    │
└─────────────────────────────────────────────────────────┘
```

## Provider Rotation Strategies

| Strategy | Description |
|----------|-------------|
| `priority` | Use providers in configured order (default) |
| `cost_first` | Pick the cheapest available provider |
| `reliability_first` | Pick the provider with lowest error rate |
| `round_robin` | Cycle through available providers |

## Installation

### 1. Install llama.cpp (for local LLM fallback)

```bash
# Option A: pip (may take 5-10 min to compile on ARM)
pip3 install llama-cpp-python

# Option B: pre-built binary
# Download from https://github.com/ggml-org/llama.cpp/releases
```

### 2. Download a local model

```bash
# Recommended for 4GB available RAM:
# Qwen2.5-3B-Instruct-Q4_K_M (~2.1GB, strong reasoning)
# Llama-3.2-3B-Instruct-Q4_K_M (~2.0GB, solid all-rounder)
# Phi-3.5-mini-instruct-Q4_K_M (~2.3GB, excellent reasoning/size)

# From HuggingFace:
wget https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf \
  -O ~/.hermes/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
```

### 3. Run the setup script

```bash
cd ~/.hermes/skills/provider-router
python3 backend/scripts/setup.py
```

### 4. Enable the monitoring cron

```bash
hermes cron create "every 2m" "provider-router-check"
```

## Configuration

Config lives at `~/.hermes/provider-router/config.json`:

```json
{
  "strategy": "priority",
  "auto_switch": true,
  "notify_on_switch": true,
  "notify_on_exhaustion": true,
  "rate_limit_cooldown_seconds": 60,
  "local_model_path": "~/.hermes/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
  "local_server_port": 8080,
  "local_threads": 4,
  "providers": [
    {
      "name": "openrouter",
      "base_url": "https://openrouter.ai/api/v1",
      "model": "openrouter/owl-alpha",
      "priority": 0
    },
    {
      "name": "nvidia",
      "base_url": "https://integrate.api.nvidia.com/v1",
      "model": "nvidia/nemotron-3-super-120b-a12b:free",
      "priority": 1
    }
  ]
}
```

## Dashboard

After installation, restart Hermes and open the Web UI. You'll see a **Provider Router** tab with:

- **📊 Dashboard** — Real-time provider status, token counts, error rates, credential health
- **⚙️ Settings** — Rotation strategy, auto-switch, rate limit cooldown
- **📋 Logs** — Notification history with severity indicators

## File Structure

```
provider-router/
├── backend/
│   ├── router_engine.py       # Core engine (monitor, router, notifier, local LLM)
│   ├── plugin_api.py          # FastAPI backend for dashboard plugin
│   └── scripts/
│       ├── setup.py           # One-time setup script
│       ├── monitor.py         # Background monitoring agent
│       └── integrate.py       # Hermes config integration
├── frontend/
│   ├── ProviderRouterDashboard.tsx  # React dashboard component
│   └── index.tsx              # Plugin entry point
├── installed-plugin/          # Files installed to Hermes plugin directory
│   ├── manifest.json
│   ├── plugin_api.py
│   └── dist/
│       ├── index.js
│       └── style.css
├── config/                    # Default configurations
├── scripts/                   # Utility scripts
├── .gitignore
└── README.md
```

## How It Works

1. **Every 2 minutes**, the cron job runs a monitoring check
2. The monitor reads cost snapshots and credential status from `~/.hermes/`
3. If a provider is exhausted or rate-limited, it's marked unavailable
4. The router selects the best available provider based on strategy
5. If all cloud providers are down, the local LLM server is started automatically
6. Notifications are written to `~/.hermes/provider-router/notifications.log`
7. In-chat notifications are delivered via the cron job's output

## Adding a New Provider

1. Add credentials: `hermes auth add <provider>`
2. Edit `~/.hermes/provider-router/config.json` to add the provider
3. The monitor will automatically pick it up on the next check

## License

MIT
