#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST="${GPS_JOYSTICK_HOST:-127.0.0.1}"
PORT="${GPS_JOYSTICK_PORT:-8765}"
URL="http://${HOST}:${PORT}"

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/gps-joystick-ubuntu"
mkdir -p "$CACHE_DIR"
LOG_FILE="$CACHE_DIR/launcher.log"

is_port_listening() {
  /usr/bin/python3 - "$HOST" "$PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(0.3)
    sys.exit(0 if s.connect_ex((host, port)) == 0 else 1)
PY
}

SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill -TERM "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}

if ! is_port_listening; then
  cd "$PROJECT_DIR"
  uv run --project "$PROJECT_DIR" gps-joystick-ubuntu --host "$HOST" --port "$PORT" --no-browser >>"$LOG_FILE" 2>&1 &
  SERVER_PID=$!
  trap cleanup EXIT INT TERM

  ready=0
  for _ in $(seq 1 60); do
    if is_port_listening; then
      ready=1
      break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      break
    fi
    sleep 0.25
  done

  if [ "$ready" -ne 1 ]; then
    printf 'GPS 搖桿伺服器啟動失敗，請查看 %s\n' "$LOG_FILE" >&2
    exit 1
  fi
fi

exec_status=0
/usr/bin/python3 "$PROJECT_DIR/scripts/open-window.py" "$URL" >>"$LOG_FILE" 2>&1 || exec_status=$?
exit "$exec_status"
