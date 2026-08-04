#!/usr/bin/env bash
set -Eeuo pipefail

require_secret() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required Railway variable ${name} is missing." >&2
    exit 64
  fi
}

require_secret CONTROL_PLANE_TUNNEL_ID
require_secret CONTROL_PLANE_API_KEY

# Keep both the MCP endpoint and tunnel health UI private inside the container.
export FASTMCP_HOST="${FASTMCP_HOST:-127.0.0.1}"
export FASTMCP_PORT="${FASTMCP_PORT:-8000}"
export MCP_SERVER_URL="${MCP_SERVER_URL:-http://127.0.0.1:${FASTMCP_PORT}/mcp}"
export HEALTH_LISTEN_ADDR="${HEALTH_LISTEN_ADDR:-127.0.0.1:8080}"
export LOG_LEVEL="${LOG_LEVEL:-info}"
export LOG_FORMAT="${LOG_FORMAT:-json}"

mcp_pid=""
tunnel_pid=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "${tunnel_pid}" ]]; then
    kill "${tunnel_pid}" 2>/dev/null || true
  fi
  if [[ -n "${mcp_pid}" ]]; then
    kill "${mcp_pid}" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

echo "Starting private Naver Blog SEO MCP server on 127.0.0.1:${FASTMCP_PORT}."
python -m src.mcp_server &
mcp_pid=$!

# Wait until the local TCP listener is ready. No API key value is printed.
python - "${FASTMCP_PORT}" <<'PY'
import socket
import sys
import time

port = int(sys.argv[1])
deadline = time.monotonic() + 60
last_error = None

while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            print(f"MCP server is accepting local connections on port {port}.")
            raise SystemExit(0)
    except OSError as exc:
        last_error = exc
        time.sleep(1)

print(f"ERROR: MCP server did not start within 60 seconds: {last_error}", file=sys.stderr)
raise SystemExit(1)
PY

echo "Starting OpenAI Secure MCP Tunnel client."
tunnel-client run &
tunnel_pid=$!

# If either process stops, terminate the other one so Railway can restart the service.
set +e
wait -n "${mcp_pid}" "${tunnel_pid}"
exit_code=$?
set -e
echo "ERROR: a required process stopped; Railway should restart the service." >&2
exit "${exit_code}"
