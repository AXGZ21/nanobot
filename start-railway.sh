#!/usr/bin/env bash
set -euo pipefail

NANOBOT_HOME="${HOME}/.nanobot"
CONFIG_PATH="${NANOBOT_HOME}/config.json"

mkdir -p "${NANOBOT_HOME}"

if [ -n "${NANOBOT_CONFIG_JSON_B64:-}" ]; then
  echo "Writing config from NANOBOT_CONFIG_JSON_B64"
  printf '%s' "${NANOBOT_CONFIG_JSON_B64}" | base64 -d > "${CONFIG_PATH}"
elif [ -n "${NANOBOT_CONFIG_JSON:-}" ]; then
  echo "Writing config from NANOBOT_CONFIG_JSON"
  printf '%s' "${NANOBOT_CONFIG_JSON}" > "${CONFIG_PATH}"
fi

if [ ! -f "${CONFIG_PATH}" ]; then
  echo "No config found. Running default setup wizard (nanobot onboard)..."
  nanobot onboard
fi

python - <<'PY'
import json
import os
from pathlib import Path

cfg_path = Path.home() / ".nanobot" / "config.json"

try:
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
except Exception:
    cfg = {}


def getp(path):
    cur = cfg
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def setp(path, value):
    cur = cfg
    for key in path[:-1]:
        node = cur.get(key)
        if not isinstance(node, dict):
            node = {}
            cur[key] = node
        cur = node
    cur[path[-1]] = value


provider_specs = [
    ("CUSTOM", "custom"),
    ("OPENROUTER", "openrouter"),
    ("OPENAI", "openai"),
    ("ANTHROPIC", "anthropic"),
    ("DEEPSEEK", "deepseek"),
    ("GROQ", "groq"),
    ("ZHIPU", "zhipu"),
    ("DASHSCOPE", "dashscope"),
    ("VLLM", "vllm"),
    ("GEMINI", "gemini"),
    ("MOONSHOT", "moonshot"),
    ("MINIMAX", "minimax"),
    ("AIHUBMIX", "aihubmix"),
    ("SILICONFLOW", "siliconflow"),
    ("VOLCENGINE", "volcengine"),
    ("OPENAI_CODEX", "openai_codex"),
    ("GITHUB_COPILOT", "github_copilot"),
]

for env_prefix, provider_key in provider_specs:
    key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
    base = os.getenv(f"{env_prefix}_API_BASE", "").strip()
    if key:
        setp(["providers", provider_key, "apiKey"], key)
    if base:
        setp(["providers", provider_key, "apiBase"], base)

# Common aliases
alias_env_map = [
    ("BRAVE_SEARCH_API_KEY", ["tools", "web", "search", "apiKey"]),
    ("DEFAULT_MODEL", ["agents", "defaults", "model"]),
    ("DEFAULT_PROVIDER", ["agents", "defaults", "provider"]),
    ("TELEGRAM_TOKEN", ["channels", "telegram", "token"]),
    ("DISCORD_TOKEN", ["channels", "discord", "token"]),
    ("SLACK_BOT_TOKEN", ["channels", "slack", "botToken"]),
    ("SLACK_APP_TOKEN", ["channels", "slack", "appToken"]),
]
for env_name, path in alias_env_map:
    value = os.getenv(env_name, "").strip()
    if value:
        setp(path, value)

if os.getenv("TELEGRAM_TOKEN", "").strip():
    setp(["channels", "telegram", "enabled"], True)
if os.getenv("DISCORD_TOKEN", "").strip():
    setp(["channels", "discord", "enabled"], True)
if os.getenv("SLACK_BOT_TOKEN", "").strip() and os.getenv("SLACK_APP_TOKEN", "").strip():
    setp(["channels", "slack", "enabled"], True)

if os.getenv("RESTRICT_TO_WORKSPACE", "").strip().lower() in {"1", "true", "yes", "on"}:
    setp(["tools", "restrictToWorkspace"], True)

# If no non-OAuth API key is present and no explicit model set, default to Codex OAuth model.
provider_key_paths = [
    ["providers", "custom", "apiKey"],
    ["providers", "openrouter", "apiKey"],
    ["providers", "openai", "apiKey"],
    ["providers", "anthropic", "apiKey"],
    ["providers", "deepseek", "apiKey"],
    ["providers", "groq", "apiKey"],
    ["providers", "zhipu", "apiKey"],
    ["providers", "dashscope", "apiKey"],
    ["providers", "vllm", "apiKey"],
    ["providers", "gemini", "apiKey"],
    ["providers", "moonshot", "apiKey"],
    ["providers", "minimax", "apiKey"],
    ["providers", "aihubmix", "apiKey"],
    ["providers", "siliconflow", "apiKey"],
    ["providers", "volcengine", "apiKey"],
]
has_non_oauth_key = any(bool(getp(path)) for path in provider_key_paths)
model = str(getp(["agents", "defaults", "model"]) or "").strip()
if not has_non_oauth_key and not model:
    setp(["agents", "defaults", "model"], "openai-codex/gpt-5.1-codex")
    setp(["agents", "defaults", "provider"], "openai_codex")

cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Config prepared: {cfg_path}")
PY

echo "Starting nanobot gateway..."
exec nanobot gateway
