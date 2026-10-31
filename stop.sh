#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/nvr.pid"

if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "⏹ Deteniendo servicio NVR (PID: $PID)..."
        pkill -P "$PID" 2>/dev/null || true
        kill "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "✅ Servicio detenido."
        exit 0
    fi
    rm -f "$PID_FILE"
fi

echo "ℹ️ No había ningún servicio NVR activo."
