#!/bin/bash
set -e

CONFIG_DIR="$HOME/.nanobot"
CONFIG_FILE="$CONFIG_DIR/config.json"

mkdir -p "$CONFIG_DIR"

# Build initial config from environment variables if config doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Creating initial config from environment variables..."
  cat > "$CONFIG_FILE" <<EOF
{
  "providers": {
    "openrouter": {
      "api_key": "${OPENROUTER_API_KEY:-}",
      "api_base": "https://openrouter.ai/api/v1"
    },
    "openai": {
      "api_key": "${OPENAI_API_KEY:-}",
      "api_base": "https://api.openai.com/v1"
    },
    "anthropic": {
      "api_key": "${ANTHROPIC_API_KEY:-}"
    }
  },
  "agents": {
    "default_model": "${DEFAULT_MODEL:-openrouter/anthropic/claude-3.5-sonnet}"
  },
  "channels": {
    "telegram": {
      "enabled": ${TELEGRAM_ENABLED:-false},
      "token": "${TELEGRAM_TOKEN:-}"
    },
    "discord": {
      "enabled": ${DISCORD_ENABLED:-false},
      "token": "${DISCORD_TOKEN:-}"
    },
    "slack": {
      "enabled": ${SLACK_ENABLED:-false},
      "bot_token": "${SLACK_BOT_TOKEN:-}",
      "app_token": "${SLACK_APP_TOKEN:-}"
    }
  }
}
EOF
  echo "Config created at $CONFIG_FILE"
fi

PORT="${PORT:-8080}"
echo "Starting NanoBot Web UI on port $PORT..."
exec uvicorn webui.main:app --host 0.0.0.0 --port "$PORT"