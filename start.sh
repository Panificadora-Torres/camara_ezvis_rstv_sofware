#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/nvr.pid"
LOG_FILE="$SCRIPT_DIR/nvr.log"
PORT="${NVR_PORT:-5050}"

echo "=========================================================="
echo "🛡️  Iniciando Sistema NVR 24/7 (EZVIZ 4K / ONVIF / RTSP)"
echo "=========================================================="

# 1. Verificar dependencias del sistema (ffmpeg y python3)
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "📦 FFmpeg no detectado. Intentando instalar..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y ffmpeg iproute2 python3-venv python3-pip
    fi
fi

# 2. Determinar binario de Python con Flask disponible (o crear .venv automáticamente en servidor nuevo)
PYTHON_BIN="python3"
if ! $PYTHON_BIN -c "import flask" >/dev/null 2>&1; then
    if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
    else
        echo "📦 Configurando entorno Python local (.venv) e instalando Flask..."
        python3 -m venv "$SCRIPT_DIR/.venv"
        "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip -q
        "$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
    fi
fi

# 3. Detener instancia previa si ya estaba corriendo
if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "🔄 Reiniciando instancia anterior (PID: $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Crear carpetas necesarias
mkdir -p "$SCRIPT_DIR/grabaciones" "$SCRIPT_DIR/capturas"

# 4. Lanzar en segundo plano solo en 127.0.0.1 (acceso interno exclusivo, oculto a la red LAN)
export NVR_BIND_HOST="127.0.0.1"
export NVR_PORT="$PORT"
nohup "$PYTHON_BIN" "$SCRIPT_DIR/visor_web.py" < /dev/null >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
disown "$NEW_PID" 2>/dev/null || true
echo "$NEW_PID" > "$PID_FILE"

sleep 2

if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "✅ Servicio NVR 24/7 ejecutándose en segundo plano"
    echo "   • PID del proceso : $NEW_PID (guardado en $PID_FILE)"
    echo "   • Archivo de logs : $LOG_FILE"
    echo "   • Interfaz Web    : http://127.0.0.1:${PORT} (Solo local, no expuesto a la LAN)"
    echo "   • Para detenerlo  : bash stop.sh"
    echo "=========================================================="
else
    echo "❌ Error al iniciar el servicio. Revisa $LOG_FILE:"
    tail -n 20 "$LOG_FILE"
    exit 1
fi
