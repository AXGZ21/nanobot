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

echo "Starting nanobot gateway..."
exec nanobot gateway
