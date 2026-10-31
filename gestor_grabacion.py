#!/usr/bin/env python3
"""
Gestor NVR 24/7 de Cámaras, Almacenamiento Circular (FIFO con cuota mínima 500 GB / 1 TB)
y Recovery de Video para Servidor Linux / Docker (Sin entorno gráfico requerido).
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMERAS_FILE = os.path.join(BASE_DIR, "camaras.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "nvr_settings.json")
DEFAULT_STORAGE_DIR = os.path.join(BASE_DIR, "grabaciones")
RECOVERED_DIR = os.path.join(DEFAULT_STORAGE_DIR, "_recuperados")

MIN_QUOTA_GB = 500  # Mínimo obligatorio de 500 GB solicitado por el usuario
DEFAULT_QUOTA_GB = 1000  # Por defecto 1000 GB (1 TB)

os.makedirs(DEFAULT_STORAGE_DIR, exist_ok=True)
os.makedirs(RECOVERED_DIR, exist_ok=True)


def load_settings() -> dict:
    default = {
        "storage_dir": DEFAULT_STORAGE_DIR,
        "max_storage_gb": DEFAULT_QUOTA_GB,  # 1000 GB (1 TB), mínimo 500 GB
        "segment_seconds": 300,  # Segmentos de 5 minutos para rotación FIFO precisa
        "record_stream": "main",  # 'main' (4K 3840x2160) o 'sub' (720p)
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default.update(data)
        except Exception:
            pass

    # Forzar siempre mínimo 500 GB
    try:
        quota = float(default.get("max_storage_gb", DEFAULT_QUOTA_GB))
    except (ValueError, TypeError):
        quota = float(DEFAULT_QUOTA_GB)
    default["max_storage_gb"] = max(float(MIN_QUOTA_GB), quota)

    # Verificar que la ruta guardada sea válida en este servidor; si viene de otra PC (/home/otro_usuario), usar ./grabaciones local
    try:
        os.makedirs(default["storage_dir"], exist_ok=True)
    except OSError:
        default["storage_dir"] = DEFAULT_STORAGE_DIR
        os.makedirs(default["storage_dir"], exist_ok=True)

    os.makedirs(os.path.join(default["storage_dir"], "_recuperados"), exist_ok=True)
    return default


def save_settings(new_settings: dict) -> dict:
    current = load_settings()
    if "storage_dir" in new_settings and str(new_settings["storage_dir"]).strip():
        current["storage_dir"] = str(new_settings["storage_dir"]).strip()
    if "segment_seconds" in new_settings:
        current["segment_seconds"] = max(60, int(new_settings["segment_seconds"]))
    if "record_stream" in new_settings:
        current["record_stream"] = new_settings["record_stream"]
    if "max_storage_gb" in new_settings:
        req_gb = float(new_settings["max_storage_gb"])
        if req_gb < MIN_QUOTA_GB:
            raise ValueError(f"El tamaño máximo de la carpeta no puede ser menor a {MIN_QUOTA_GB} GB.")
        current["max_storage_gb"] = req_gb

    os.makedirs(current["storage_dir"], exist_ok=True)
    os.makedirs(os.path.join(current["storage_dir"], "_recuperados"), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    return current


def load_cameras() -> list[dict]:
    """Carga las cámaras configuradas."""
    if os.path.exists(CAMERAS_FILE):
        try:
            with open(CAMERAS_FILE, "r", encoding="utf-8") as f:
                cams = json.load(f)
                if isinstance(cams, list) and cams:
                    return cams
        except Exception:
            pass

    initial = [
        {
            "id": "cam_184",
            "name": "Cámara EZVIZ 4K #1 (SN: BK7710662)",
            "ip": "192.168.1.184",
            "mac": "f4:70:18:6c:47:0e",
            "brand": "EZVIZ",
            "model": "CS-H6c-R200-8H8WFL",
            "serial": "BK7710662",
            "port": 554,
            "user": "admin",
            "password": "UPTXPQ",
            "rtsp_main": "rtsp://admin:UPTXPQ@192.168.1.184:554/ch1/main",
            "rtsp_sub": "rtsp://admin:UPTXPQ@192.168.1.184:554/ch1/sub",
            "width": 3840,
            "height": 2160,
            "codec": "hevc",
            "auto_record": False,
        },
        {
            "id": "cam_156",
            "name": "Cámara EZVIZ 4K #2 (SN: BK0605654)",
            "ip": "192.168.1.156",
            "mac": "64:24:4d:d3:b7:cc",
            "brand": "EZVIZ",
            "model": "CS-H6c-R200-8H8WFL",
            "serial": "BK0605654",
            "port": 554,
            "user": "admin",
            "password": "QJPTRT",
            "rtsp_main": "rtsp://admin:QJPTRT@192.168.1.156:554/ch1/main",
            "rtsp_sub": "rtsp://admin:QJPTRT@192.168.1.156:554/ch1/sub",
            "width": 3840,
            "height": 2160,
            "codec": "hevc",
            "auto_record": False,
        },
        {
            "id": "cam_152",
            "name": "Cámara EZVIZ 4K #3 (SN: BK7710943)",
            "ip": "192.168.1.152",
            "mac": "f4:70:18:6c:fe:ca",
            "brand": "EZVIZ",
            "model": "CS-H6c-R200-8H8WFL",
            "serial": "BK7710943",
            "port": 554,
            "user": "admin",
            "password": "FKVNOP",
            "rtsp_main": "rtsp://admin:FKVNOP@192.168.1.152:554/ch1/main",
            "rtsp_sub": "rtsp://admin:FKVNOP@192.168.1.152:554/ch1/sub",
            "width": 3840,
            "height": 2160,
            "codec": "hevc",
            "auto_record": False,
        },
    ]
    save_cameras(initial)
    return initial


def save_cameras(cameras: list[dict]) -> None:
    with open(CAMERAS_FILE, "w", encoding="utf-8") as f:
        json.dump(cameras, f, indent=2, ensure_ascii=False)


class RecordingManager:
    """
    Motor de grabación continua 24/7 con rotación circular automática (FIFO)
    basada en el límite de GB configurado (mínimo 500 GB).
    """

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_flags: dict[str, bool] = {}
        self._lock = threading.Lock()
        self.deleted_segments_count = 0
        self.deleted_bytes_total = 0

        # Iniciar hilo de limpieza circular FIFO y auto-arranque 24/7
        self._cleanup_thread = threading.Thread(target=self._storage_cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def start_auto_record_cameras(self) -> None:
        """Inicia automáticamente la grabación 24/7 de las cámaras marcadas con auto_record=True."""
        for cam in load_cameras():
            if cam.get("auto_record", False):
                self.start_recording(cam["id"], persist_24_7=False)

    def is_recording(self, cam_id: str) -> bool:
        with self._lock:
            proc = self._procs.get(cam_id)
            return proc is not None and proc.poll() is None

    def start_recording(self, cam_id: str, persist_24_7: bool = True) -> tuple[bool, str]:
        cams = load_cameras()
        cameras = {c["id"]: c for c in cams}
        if cam_id not in cameras:
            return False, "Cámara no encontrada"

        if persist_24_7:
            for c in cams:
                if c["id"] == cam_id:
                    c["auto_record"] = True
            save_cameras(cams)

        if self.is_recording(cam_id):
            return True, "La grabación 24/7 ya está activa"

        cam = cameras[cam_id]
        self._stop_flags[cam_id] = False
        t = threading.Thread(target=self._record_loop, args=(cam_id,), daemon=True)
        self._threads[cam_id] = t
        t.start()
        return True, f"Grabación continua 24/7 activada para {cam['name']}"

    def stop_recording(self, cam_id: str, persist_24_7: bool = True) -> tuple[bool, str]:
        self._stop_flags[cam_id] = True
        if persist_24_7:
            cams = load_cameras()
            for c in cams:
                if c["id"] == cam_id:
                    c["auto_record"] = False
            save_cameras(cams)

        with self._lock:
            proc = self._procs.pop(cam_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except Exception:
                proc.kill()
        return True, "Grabación 24/7 detenida"

    def _record_loop(self, cam_id: str) -> None:
        """Bucle resiliente 24/7: reconecta automáticamente si la cámara o la red se corta."""
        while not self._stop_flags.get(cam_id, False):
            cams = {c["id"]: c for c in load_cameras()}
            cam = cams.get(cam_id)
            if not cam:
                break

            settings = load_settings()
            storage_dir = settings["storage_dir"]
            seg_time = int(settings.get("segment_seconds", 300))
            stream_type = settings.get("record_stream", "main")
            rtsp_url = cam["rtsp_main"] if stream_type == "main" else cam["rtsp_sub"]

            cam_dir = os.path.join(storage_dir, cam_id)
            os.makedirs(cam_dir, exist_ok=True)
            out_pattern = os.path.join(cam_dir, "%Y-%m-%d_%H-%M-%S.mp4")

            cmd = [
                "ffmpeg",
                "-loglevel", "warning",
                "-fflags", "+genpts",
                "-rtsp_transport", "tcp",
                "-timeout", "10000000",
                "-i", rtsp_url,
                "-c:v", "copy",
                "-c:a", "aac",
                "-f", "segment",
                "-segment_time", str(seg_time),
                "-segment_atclocktime", "1",
                "-reset_timestamps", "1",
                "-strftime", "1",
                "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
                out_pattern,
            ]
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                with self._lock:
                    self._procs[cam_id] = proc
                proc.wait()
            except Exception:
                pass
            if not self._stop_flags.get(cam_id, False):
                time.sleep(5)

    def _storage_cleanup_loop(self) -> None:
        """Monitorea cada 30 segundos el tamaño de la carpeta y elimina los videos más antiguos (FIFO)."""
        while True:
            try:
                self.enforce_storage_quota()
            except Exception:
                pass
            time.sleep(30)

    def enforce_storage_quota(self) -> dict:
        """
        Comprueba si el uso total de la carpeta de grabaciones supera max_storage_gb (mínimo 500 GB).
        Si lo supera, elimina automáticamente los segmentos más antiguos (FIFO) hasta quedar por debajo del límite.
        """
        settings = load_settings()
        storage_dir = settings["storage_dir"]
        max_gb = max(float(MIN_QUOTA_GB), float(settings.get("max_storage_gb", DEFAULT_QUOTA_GB)))
        max_bytes = int(max_gb * (1024 ** 3))

        all_files = []
        total_bytes = 0

        if os.path.exists(storage_dir):
            for root, _dirs, files in os.walk(storage_dir):
                # No borrar archivos ya exportados manualmente en _recuperados
                if "_recuperados" in root:
                    continue
                for fname in files:
                    if not fname.endswith((".mp4", ".ts", ".mkv")):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        st = os.stat(fpath)
                        total_bytes += st.st_size
                        all_files.append((st.st_mtime, st.st_size, fpath))
                    except OSError:
                        continue

        deleted_now = 0
        freed_now = 0

        if total_bytes > max_bytes:
            # Ordenar de más antiguo a más reciente (menor mtime primero)
            all_files.sort(key=lambda x: x[0])
            # Dejar al menos un margen de 1% o borrar hasta estar <= max_bytes
            target_bytes = int(max_bytes * 0.99)
            for _mtime, fsize, fpath in all_files:
                if total_bytes <= target_bytes:
                    break
                try:
                    os.remove(fpath)
                    total_bytes -= fsize
                    deleted_now += 1
                    freed_now += fsize
                    self.deleted_segments_count += 1
                    self.deleted_bytes_total += fsize
                except OSError:
                    continue

        return {
            "used_bytes": total_bytes,
            "max_bytes": max_bytes,
            "deleted_now": deleted_now,
            "freed_bytes_now": freed_now,
        }

    def get_storage_stats(self) -> dict:
        """Retorna métricas detalladas del almacenamiento de grabaciones y disco físico."""
        settings = load_settings()
        storage_dir = settings["storage_dir"]
        max_gb = max(float(MIN_QUOTA_GB), float(settings.get("max_storage_gb", DEFAULT_QUOTA_GB)))
        quota_info = self.enforce_storage_quota()

        used_bytes = quota_info["used_bytes"]
        used_gb = round(used_bytes / (1024 ** 3), 2)
        pct = round((used_gb / max_gb) * 100, 2) if max_gb > 0 else 0.0

        disk_total_gb = 0.0
        disk_free_gb = 0.0
        try:
            du = shutil.disk_usage(storage_dir)
            disk_total_gb = round(du.total / (1024 ** 3), 2)
            disk_free_gb = round(du.free / (1024 ** 3), 2)
        except Exception:
            pass

        return {
            "storage_dir": storage_dir,
            "used_bytes": used_bytes,
            "used_gb": used_gb,
            "max_storage_gb": max_gb,
            "min_allowed_gb": MIN_QUOTA_GB,
            "usage_percent": min(100.0, pct),
            "disk_total_gb": disk_total_gb,
            "disk_free_gb": disk_free_gb,
            "deleted_segments_total": self.deleted_segments_count,
            "deleted_gb_total": round(self.deleted_bytes_total / (1024 ** 3), 2),
        }

    def list_recordings(self, cam_id: str = "", date_filter: str = "") -> list[dict]:
        """Lista todos los segmentos de video almacenados localmente (soporta subcarpetas por fecha)."""
        settings = load_settings()
        storage_dir = settings["storage_dir"]
        cameras = {c["id"]: c["name"] for c in load_cameras()}
        items = []

        if not os.path.exists(storage_dir):
            return items

        for cid in sorted(os.listdir(storage_dir)):
            if cid.startswith("_"):
                continue
            if cam_id and cid != cam_id:
                continue
            cpath = os.path.join(storage_dir, cid)
            if not os.path.isdir(cpath):
                continue

            for root, _dirs, files in os.walk(cpath):
                for fname in files:
                    if not fname.endswith((".mp4", ".ts", ".mkv")):
                        continue
                    if date_filter and not fname.startswith(date_filter):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        st = os.stat(fpath)
                    except OSError:
                        continue
                    size_mb = round(st.st_size / (1024 * 1024), 2)
                    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", fname)
                    date_str = m.group(1) if m else datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
                    time_str = m.group(2).replace("-", ":") if m else datetime.datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S")
                    rel_path = os.path.relpath(fpath, storage_dir).replace("\\", "/")
                    items.append({
                        "cam_id": cid,
                        "cam_name": cameras.get(cid, cid),
                        "filename": fname,
                        "rel_path": rel_path,
                        "full_path": fpath,
                        "date": date_str,
                        "time": time_str,
                        "size_mb": size_mb,
                        "mtime": st.st_mtime,
                    })

        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items

    def recover_video_file(self, rel_path: str) -> dict:
        """Reconstruye la tabla de índices MP4 (moov atom / faststart) sin perder calidad."""
        settings = load_settings()
        storage_dir = os.path.abspath(settings["storage_dir"])
        recovered_dir = os.path.join(storage_dir, "_recuperados")
        os.makedirs(recovered_dir, exist_ok=True)

        src = os.path.abspath(os.path.join(storage_dir, rel_path))
        if not src.startswith(storage_dir) or not os.path.exists(src):
            return {"ok": False, "error": "Archivo original no encontrado"}

        base_name = os.path.basename(src)
        cid = rel_path.split("/")[0]
        out_name = f"RECOVERED_{cid}_{base_name}"
        out_path = os.path.join(recovered_dir, out_name)

        cmd = [
            "ffmpeg", "-y",
            "-err_detect", "ignore_err",
            "-i", src,
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            out_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0 and os.path.exists(out_path):
                size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 2)
                return {
                    "ok": True,
                    "filename": out_name,
                    "path": out_path,
                    "size_mb": size_mb,
                    "message": f"Video recuperado y reindexado con éxito ({size_mb} MB)",
                }
            return {"ok": False, "error": res.stderr[-300:] if res.stderr else "Error en FFmpeg"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def recover_time_range(self, cam_id: str, date_str: str, start_time: str, end_time: str) -> dict:
        """Une y repara todos los segmentos de una cámara en una fecha y rango de horas."""
        settings = load_settings()
        recovered_dir = os.path.join(os.path.abspath(settings["storage_dir"]), "_recuperados")
        os.makedirs(recovered_dir, exist_ok=True)

        recs = self.list_recordings(cam_id=cam_id, date_filter=date_str)
        if not recs:
            return {"ok": False, "error": f"No hay grabaciones para {cam_id} en la fecha {date_str}"}

        start_norm = start_time.strip()[:5]
        end_norm = end_time.strip()[:5]
        selected = []
        for r in sorted(recs, key=lambda x: x["time"]):
            t_hhmm = r["time"][:5]
            if start_norm <= t_hhmm <= end_norm:
                selected.append(r["full_path"])

        if not selected:
            return {
                "ok": False,
                "error": f"No se encontraron segmentos entre {start_norm} y {end_norm} el {date_str}",
            }

        list_file = os.path.join(recovered_dir, f"concat_{cam_id}_{int(time.time())}.txt")
        out_name = f"CLIP_{cam_id}_{date_str}_{start_norm.replace(':','')}_a_{end_norm.replace(':','')}.mp4"
        out_path = os.path.join(recovered_dir, out_name)

        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for p in selected:
                    safe_p = p.replace("'", "'\\''")
                    f.write(f"file '{safe_p}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-err_detect", "ignore_err",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c:v", "copy",
                "-c:a", "copy",
                "-movflags", "+faststart",
                out_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if os.path.exists(list_file):
                os.remove(list_file)

            if res.returncode == 0 and os.path.exists(out_path):
                size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 2)
                return {
                    "ok": True,
                    "filename": out_name,
                    "path": out_path,
                    "segments_merged": len(selected),
                    "size_mb": size_mb,
                    "message": f"Se unieron y recuperaron {len(selected)} segmentos ({size_mb} MB).",
                }
            return {"ok": False, "error": res.stderr[-300:] if res.stderr else "Fallo al unir segmentos"}
        except Exception as e:
            if os.path.exists(list_file):
                os.remove(list_file)
            return {"ok": False, "error": str(e)}


recorder = RecordingManager()
recorder.start_auto_record_cameras()
