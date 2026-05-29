#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${SELENIUM_COMPOSE_FILE:-docker-compose.cloud.yml}"
GRID_URL="${SELENIUM_GRID_URL:-http://localhost:4444}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
GRID_WAIT_TIMEOUT="${GRID_WAIT_TIMEOUT:-180}"
HEADLESS="${HEADLESS:-true}"
LOG_FILE="${SELENIUM_LOG_FILE:-selenium-grid-logs.txt}"

cleanup() {
  local exit_code=$?

  echo "Collecting Selenium Grid logs..."
  docker compose -f "$COMPOSE_FILE" ps || true
  docker compose -f "$COMPOSE_FILE" logs --no-color > "$LOG_FILE" 2>&1 || true
  docker compose -f "$COMPOSE_FILE" down -v || true

  exit "$exit_code"
}
trap cleanup EXIT

wait_for_grid() {
  local deadline=$((SECONDS + GRID_WAIT_TIMEOUT))

  echo "Waiting for Selenium Grid at $GRID_URL..."
  while true; do
    if curl -fsS "$GRID_URL/status" | grep -q '"ready"[[:space:]]*:[[:space:]]*true'; then
      echo "Selenium Grid is ready."
      return 0
    fi

    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for Selenium Grid after ${GRID_WAIT_TIMEOUT}s." >&2
      return 1
    fi

    sleep 2
  done
}

echo "Starting Selenium Grid with $COMPOSE_FILE..."
docker compose -f "$COMPOSE_FILE" up -d

wait_for_grid

echo "Running Selenium test suite..."
HEADLESS="$HEADLESS" SELENIUM_GRID_URL="$GRID_URL" "$PYTHON_BIN" test_business.py
