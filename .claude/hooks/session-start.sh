#!/bin/bash
# Installs the project's dependencies at the start of a Claude Code cloud session, so lint,
# tests and the web build work without an environment setup script. Idempotent: uv and npm
# skip what is already installed, and the container is cached after the first run.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
  fi
fi

# Python 3.12 + core deps + LLM gateway (same as `make setup`), from uv.lock.
uv sync --extra llm

# Review page (web/). npm install reuses the cached node_modules; versions come from the lock.
if [ -f web/package.json ]; then
  (cd web && npm install --no-audit --no-fund)
fi
