#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARG1="${1:-main}"
CUSTOM_URL="${2:-}"
ZOOM_FACTOR="${3:-1}"

if [ -n "$CUSTOM_URL" ]; then
    RTSP_URL="$CUSTOM_URL"
    TITLE="Cámara RTSP ($ARG1)"
else
    CAMERA_IP="$(python3 "$SCRIPT_DIR/buscar_camara.py" --ip-only)"
    if [ "$ARG1" = "sub" ] || [ "$ARG1" = "hd" ]; then
        RTSP_PATH="/ch1/sub"
        TITLE="Cámara EZVIZ (HD 720p) - $CAMERA_IP"
    else
        RTSP_PATH="/ch1/main"
        TITLE="Cámara EZVIZ 4K Real (3840x2160) - $CAMERA_IP"
    fi
    RTSP_URL="rtsp://admin:UPTXPQ@${CAMERA_IP}:554${RTSP_PATH}"
fi

VF_ARGS=()
if [ "$ZOOM_FACTOR" != "1" ] && [ -n "$ZOOM_FACTOR" ]; then
    # Recorte digital centrado sobre el sensor 4K (3840x2160)
    VF_ARGS=(-vf "crop=iw/${ZOOM_FACTOR}:ih/${ZOOM_FACTOR}:(iw-iw/${ZOOM_FACTOR})/2:(ih-ih/${ZOOM_FACTOR})/2")
    TITLE="${TITLE} [Zoom ${ZOOM_FACTOR}x]"
fi

echo "🎥 Abriendo stream en resolución nativa: $RTSP_URL"
exec ffplay \
    -nostats \
    -rtsp_transport tcp \
    -fflags nobuffer \
    -flags low_delay \
    -framedrop \
    "${VF_ARGS[@]}" \
    -window_title "$TITLE" \
    "$RTSP_URL"
