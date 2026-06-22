---
name: provider-router
description: Intelligent provider routing with token tracking, rate limit awareness, multi-key rotation, and local LLM fallback. Monitors all cloud providers and automatically switches when limits are reached.
version: 1.0.0
author: OWL
license: MIT
metadata:
  hermes:
    tags: [provider-router, token-tracker, rate-limit, local-llm, fallback, multi-provider]
---

# Provider Router

Intelligent multi-provider routing system for Hermes Agent. Tracks token usage per key/provider/model, monitors rate limits in real-time, rotates API keys, switches providers when limits are hit, and falls back to a local Gemma 3 4B model when all cloud providers are exhausted.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Hermes Agent                              │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Token Tracker │───▶│   Router     │───▶│  Notifier    │  │
│  │ (SQLite)      │    │ (Priority)   │    │ (In-chat)    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    │          │
│         ▼                    ▼                    ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Usage DB     │    │ Provider DB  │    │ Events Log   │  │
│  │ (usage.db)   │    │ (JSON)       │    │ (SQLite)     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                              │                               │
│              ┌───────────────┼───────────────┐               │
│              ▼               ▼               ▼               │
│        ┌──────────┐   ┌──────────┐   ┌──────────┐          │
│        │OpenRouter│   │  Groq    │   │  Local   │          │
│        │(2+ keys) │   │  Mistral │   │  Gemma3  │          │
│        │          │   │  NVIDIA  │   │  4B Q4   │          │
│        └──────────┘   │  OpCode  │   └──────────┘          │
│                       │  Ollama  │                          │
│                       └──────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

## Provider Priority Order

| Priority | Provider | Free Tier Limits | Notes |
|----------|----------|-----------------|-------|
| 1 | OpenRouter | 20 RPM, 50 RPD (free) / 1000 RPD ($10+) | Multiple keys supported |
| 2 | Groq | 30 RPM, 6K TPM, 14.4K RPD | Fast inference |
| 3 | Mistral | 5 RPM (free) / 60 RPM (scale) | Per-model limits |
| 4 | NVIDIA NIM | 40 RPM, 1000 credits | Up to 5000 credits on request |
| 5 | OpenCode Zen | Dynamic | Shared pool |
| 6 | Ollama Cloud | Session/weekly limits | 5hr session reset |
| 99 | Local (Gemma 3 4B) | Unlimited | Hardware-bounded fallback |

## Rate Limit Database

All provider limits are stored in `provider_db.json`. Each provider has:
- Per-minute request limits (RPM)
- Per-day request limits (RPD)
- Per-minute token limits (TPM)
- Model-specific costs and context lengths
- Tier information (free/paid)

## When to Use This Skill

Load this skill when:
- User asks about token usage or provider status
- User wants to add/rotate API keys
- User wants to configure the local LLM fallback
- User asks why a provider was switched
- User wants to see usage statistics
- Any provider rate limit event occurs

## Workflows

### Check Provider Status

```bash
cd /root/hermes/workspace/projects/provider-router
python3 router.py status
```

Returns: current provider, exhausted providers, usage summary, recent events.

### Record Usage (called after each API call)

```bash
python3 router.py report <provider> <model> <input_tokens> <output_tokens> [key_id]
```

Example:
```bash
python3 router.py report openrouter owl-alpha 1500 800 key_1
```

### Get Next Available Provider

```bash
python3 router.py next [preferred_model]
```

Returns the best available provider, model, and key_id.

### View Recent Events

```bash
python3 router.py events [limit]
```

### Reset Exhausted Status

```bash
python3 router.py reset [provider]
```

Use when rate limit windows have reset (e.g., new day, new minute).

### Add API Key

```bash
python3 router.py add-key <provider> <key_id> <api_key> [tier]
```

Example:
```bash
python3 router.py add-key openrouter key_2 sk-or-v1-xxx free
```

### View Usage Summary

```bash
python3 router.py summary [provider]
```

## Integration with Hermes

### Automatic Provider Switching

The router is designed to be called by Hermes cron jobs and hooks:

1. **Cron job (every 5 min)**: Check rate limits, reset expired windows, notify if any provider is near limit
2. **Post-API hook**: Record usage after each call, check if provider just got exhausted
3. **Pre-API hook**: Get next available provider before making a call

### Local LLM Fallback

When all cloud providers are exhausted:
1. Router activates local Gemma 3 4B via llama.cpp server
2. User is notified: "🏠 Local LLM activated — all cloud providers exhausted"
3. Local model handles simple tasks and switching logic
4. When cloud limits reset, router switches back automatically
5. User is notified: "☁️ Cloud provider restored"

### Notification Events

| Event | Severity | When |
|-------|----------|------|
| `provider_switched` | ℹ️ Info | Router picks a new provider |
| `key_rotated` | ℹ️ Info | OpenRouter key pool rotation |
| `rate_limit_warning` | ⚠️ Warning | 80% of rate limit reached |
| `provider_exhausted` | ⚠️ Warning | Provider hit hard limit |
| `local_fallback_activated` | 🔴 Critical | All cloud providers exhausted |
| `local_fallback_deactivated` | ℹ️ Info | Cloud provider restored |

## Files

| File | Purpose |
|------|---------|
| `provider_db.json` | Provider rate limits, models, costs |
| `router.py` | Core routing engine + CLI |
| `notifier.py` | Notification formatting + delivery |
| `usage.db` | SQLite database (auto-created) |
| `router_state.json` | Current router state (auto-created) |

## Local LLM Setup (Gemma 3 4B)

### Install llama.cpp

```bash
# Check if already installed
which llama-server || which llama-cli

# Install on Android/Termux
pkg install cmake
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build
cmake --build build --config Release
```

### Download Gemma 3 4B GGUF

```bash
# From Hugging Face (bartowski has good quants)
# Recommended: Q4_K_M quant (~2.5GB)
llama-server -hf bartowski/gemma-3-4b-it-GGUF:Q4_K_M \
  --port 8080 --host 0.0.0.0 \
  -c 8192
```

### Verify Local Server

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'
```

## Configuration

To add a new provider:
1. Add entry to `provider_db.json` under `providers`
2. Set rate limits, models, priority
3. Add API key via `router.py add-key`

To change provider priority:
1. Edit `priority` field in `provider_db.json`
2. Lower number = higher priority

## Troubleshooting

- **"All providers exhausted"**: Check `router.py status` to see which providers are marked exhausted and why. Use `router.py reset` to clear if windows have expired.
- **Local LLM not responding**: Check if `llama-server` is running on port 8080. Restart if needed.
- **Usage not being recorded**: Ensure `usage.db` is writable. Check `router.py events` for errors.
