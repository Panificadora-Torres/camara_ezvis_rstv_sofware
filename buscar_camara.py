#!/usr/bin/env python3
"""
Buscador automático de la cámara EZVIZ (Código: UPTXPQ, MAC: f4:70:18:6c:47:0e)
Identifica la IP correcta en la red local aunque haya muchas otras cámaras y el DHCP cambie la IP.
"""
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys

CAMERA_CODE = "UPTXPQ"
CAMERA_USER = "admin"
KNOWN_MAC = "f4:70:18:6c:47:0e"
DEFAULT_IP = "192.168.1.184"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camara_config.json")


def test_rtsp_auth(ip: str, code: str = CAMERA_CODE, timeout: float = 4.0) -> bool:
    """Verifica si la IP responde con éxito al stream RTSP usando el código de verificación."""
    url = f"rtsp://{CAMERA_USER}:{code}@{ip}:554/ch1/sub"
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-rtsp_transport", "tcp",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode == 0 and "codec_name=" in res.stdout
    except Exception:
        return False


def find_ip_by_mac(mac: str = KNOWN_MAC) -> str | None:
    """Busca la dirección MAC conocida en la tabla ARP del sistema."""
    try:
        res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=3)
        for line in res.stdout.splitlines():
            if mac.lower() in line.lower():
                parts = line.split()
                if parts:
                    return parts[0]
    except Exception:
        pass
    return None


def is_port_open(ip: str, port: int = 554, timeout: float = 0.4) -> bool:
    """Comprueba rápidamente si el puerto TCP 554 (RTSP) está abierto."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_local_subnet_prefix() -> str:
    """Obtiene el prefijo de la red local (ej. 192.168.1.)."""
    try:
        res = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True, timeout=3)
        m = re.search(r"via\s+(\d+\.\d+\.\d+)\.\d+", res.stdout)
        if m:
            return m.group(1) + "."
    except Exception:
        pass
    return "192.168.1."


def discover_camera(force_scan: bool = False) -> dict:
    """Encuentra la IP actual de la cámara EZVIZ y guarda la configuración."""
    if not force_scan:
        # 1. Probar IP guardada o por defecto
        saved_ip = DEFAULT_IP
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved_ip = json.load(f).get("ip", DEFAULT_IP)
            except Exception:
                pass

        if is_port_open(saved_ip) and test_rtsp_auth(saved_ip):
            return save_config(saved_ip)

        # 2. Probar buscando por dirección MAC en tabla ARP
        mac_ip = find_ip_by_mac(KNOWN_MAC)
        if mac_ip and mac_ip != saved_ip and is_port_open(mac_ip) and test_rtsp_auth(mac_ip):
            return save_config(mac_ip)

    # 3. Escanear toda la subred en el puerto 554 y probar autenticación con UPTXPQ
    prefix = get_local_subnet_prefix()
    all_ips = [f"{prefix}{i}" for i in range(1, 255)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        open_554_ips = [ip for ip, ok in zip(all_ips, ex.map(is_port_open, all_ips)) if ok]

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for ip, ok in zip(open_554_ips, ex.map(test_rtsp_auth, open_554_ips)):
            if ok:
                return save_config(ip)

    raise RuntimeError("No se encontró la cámara EZVIZ con código UPTXPQ en la red local.")


def save_config(ip: str) -> dict:
    data = {
        "ip": ip,
        "mac": KNOWN_MAC,
        "port": 554,
        "user": CAMERA_USER,
        "code": CAMERA_CODE,
        "rtsp_main": f"rtsp://{CAMERA_USER}:{CAMERA_CODE}@{ip}:554/ch1/main",
        "rtsp_sub": f"rtsp://{CAMERA_USER}:{CAMERA_CODE}@{ip}:554/ch1/sub",
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return data


if __name__ == "__main__":
    force = "--scan" in sys.argv
    quiet = "--ip-only" in sys.argv
    try:
        info = discover_camera(force_scan=force)
        if quiet:
            print(info["ip"])
        else:
            print(f"✅ Cámara EZVIZ identificada con éxito:")
            print(f"   • Dirección IP : {info['ip']}")
            print(f"   • Dirección MAC: {info['mac']}")
            print(f"   • Código       : {info['code']}")
            print(f"   • RTSP 4K Main : {info['rtsp_main']}")
            print(f"   • RTSP HD Sub  : {info['rtsp_sub']}")
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
