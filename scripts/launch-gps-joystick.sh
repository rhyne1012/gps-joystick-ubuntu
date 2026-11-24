#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST="${GPS_JOYSTICK_HOST:-127.0.0.1}"
PORT="${GPS_JOYSTICK_PORT:-8765}"
URL="http://${HOST}:${PORT}"

is_port_listening() {
  python3 - "$HOST" "$PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(0.3)
    sys.exit(0 if s.connect_ex((host, port)) == 0 else 1)
PY
}

if is_port_listening; then
  printf 'GPS 搖桿伺服器已在執行中：%s\n正在開啟瀏覽器...\n' "$URL"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
  fi
  sleep 1
  exit 0
fi

cd "$PROJECT_DIR"
set +e
uv run --project "$PROJECT_DIR" gps-joystick-ubuntu --host "$HOST" --port "$PORT"
status=$?
set -e

if [ "$status" -ne 0 ]; then
  printf '\nGPS 搖桿已結束（exit code %d）。\n' "$status"
  read -r -p "啟動失敗，按 Enter 關閉視窗..."
  exit "$status"
fi
