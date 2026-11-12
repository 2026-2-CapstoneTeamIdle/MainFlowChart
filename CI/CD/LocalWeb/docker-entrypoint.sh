#!/usr/bin/env bash
set -euo pipefail

display="${DISPLAY:-:99}"
xvfb_log="${TMPDIR:-/tmp}/mainflow-xvfb.log"

Xvfb "$display" -screen 0 1920x1080x24 -nolisten tcp >"$xvfb_log" 2>&1 &
xvfb_pid=$!

cleanup() {
  kill "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 50); do
  if [ -S "/tmp/.X11-unix/X${display#:}" ]; then
    exec "$@"
  fi
  if ! kill -0 "$xvfb_pid" 2>/dev/null; then
    echo "Xvfb failed to start:" >&2
    cat "$xvfb_log" >&2 || true
    exit 1
  fi
  sleep 0.1
done

echo "Xvfb did not become ready on ${display}." >&2
cat "$xvfb_log" >&2 || true
exit 1
