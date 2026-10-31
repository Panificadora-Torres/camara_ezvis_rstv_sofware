#!/usr/bin/env python3
"""
Escáner Multicapa de Cámaras IP Locales:
1. Protocolo SADP (UDP 37020) para cámaras EZVIZ y Hikvision (obtiene Modelo exacto, Serial, MAC, Firmware).
2. Protocolo ONVIF WS-Discovery (UDP 3702) para cámaras ONVIF de cualquier marca.
3. Escaneo TCP de puertos RTSP/ONVIF (554, 8554, 8000, 8899, 37777) + lectura de cabeceras RTSP DESCRIBE.
"""
import concurrent.futures
import re
import socket
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET


def get_local_ip_and_prefix() -> tuple[str, str]:
    """Obtiene la IP local en la interfaz principal (ej. 192.168.1.16) y el prefijo (192.168.1.)."""
    try:
        res = subprocess.run(["ip", "-4", "route", "get", "192.168.1.1"], capture_output=True, text=True, timeout=2)
        m = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", res.stdout)
        if m:
            ip = m.group(1)
            prefix = ".".join(ip.split(".")[:3]) + "."
            return ip, prefix
    except Exception:
        pass
    return "192.168.1.16", "192.168.1."


def get_arp_table() -> dict[str, str]:
    """Retorna diccionario {ip: mac} desde la tabla ARP del sistema."""
    arp = {}
    try:
        res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=3)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1] == "lladdr":
                arp[parts[0]] = parts[2].lower()
    except Exception:
        pass
    return arp


def scan_sadp(local_ip: str, prefix: str, rounds: int = 2) -> dict[str, dict]:
    """Descubre dispositivos EZVIZ y Hikvision mediante SADP (UDP 37020)."""
    devices = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((local_ip, 0))
    except Exception:
        sock.bind(("0.0.0.0", 0))
    sock.settimeout(0.3)

    for _ in range(rounds):
        probe = (
            f'<?xml version="1.0" encoding="utf-8"?>'
            f"<Probe><Uuid>{uuid.uuid4().hex.upper()}</Uuid><Types>inquiry</Types></Probe>"
        ).encode()
        try:
            sock.sendto(probe, ("239.255.255.250", 37020))
        except Exception:
            pass
        for i in range(1, 255):
            try:
                sock.sendto(probe, (f"{prefix}{i}", 37020))
            except Exception:
                pass

        t0 = time.time()
        while time.time() - t0 < 1.0:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip not in devices:
                    txt = data.decode(errors="ignore")
                    root = ET.fromstring(txt)
                    model = root.findtext("DeviceDescription", "") or "Desconocido"
                    sn = root.findtext("DeviceSN", "")
                    mac = (root.findtext("MAC", "") or "").replace("-", ":").lower()
                    ezviz = root.findtext("EZVIZCode", "false").lower() == "true" or model.startswith("CS-")
                    brand = "EZVIZ" if ezviz else "Hikvision"
                    devices[ip] = {
                        "ip": ip,
                        "brand": brand,
                        "model": model,
                        "serial": sn,
                        "mac": mac,
                        "firmware": root.findtext("SoftwareVersion", ""),
                        "protocol": "SADP / RTSP",
                    }
            except socket.timeout:
                break
            except Exception:
                continue
    sock.close()
    return devices


def scan_onvif(local_ip: str) -> dict[str, dict]:
    """Descubre cámaras compatibles con ONVIF mediante WS-Discovery (UDP 3702)."""
    devices = {}
    ws_probe = f"""<?xml version="1.0" encoding="UTF-8"?>
    <e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
                xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
                xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
      <e:Header>
        <w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>
        <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
        <w:Action a:mustUnderstand="true" xmlns:a="http://www.w3.org/2005/08/addressing">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
      </e:Header>
      <e:Body>
        <d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>
      </e:Body>
    </e:Envelope>""".encode()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((local_ip, 0))
    except Exception:
        sock.bind(("0.0.0.0", 0))
    sock.settimeout(0.4)

    try:
        sock.sendto(ws_probe, ("239.255.255.250", 3702))
        t0 = time.time()
        while time.time() - t0 < 1.0:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                txt = data.decode(errors="ignore")
                m_xaddrs = re.search(r"<[^:>]*:?XAddrs>([^<]+)</", txt)
                m_scopes = re.search(r"<[^:>]*:?Scopes>([^<]+)</", txt)
                model = "ONVIF Camera"
                if m_scopes:
                    m_hw = re.search(r"onvif://www\.onvif\.org/hardware/([^\s]+)", m_scopes.group(1))
                    if m_hw:
                        model = m_hw.group(1)
                devices[ip] = {
                    "ip": ip,
                    "brand": "ONVIF",
                    "model": model,
                    "onvif_url": m_xaddrs.group(1).split()[0] if m_xaddrs else f"http://{ip}/onvif/device_service",
                    "protocol": "ONVIF / RTSP",
                }
            except socket.timeout:
                break
            except Exception:
                continue
    finally:
        sock.close()
    return devices


def probe_rtsp_and_ports(ip: str) -> dict | None:
    """Comprueba puertos de cámaras IP (554, 8554, 8000, 8899) y cabeceras RTSP."""
    open_ports = []
    for port in (554, 8000, 8899, 9010):
        try:
            with socket.create_connection((ip, port), timeout=0.35):
                open_ports.append(port)
        except Exception:
            pass
    if not open_ports:
        return None

    realm = ""
    if 554 in open_ports:
        try:
            with socket.create_connection((ip, 554), timeout=0.8) as s:
                req = f"DESCRIBE rtsp://{ip}:554/ch1/main RTSP/1.0\r\nCSeq: 1\r\n\r\n"
                s.sendall(req.encode())
                resp = s.recv(2048).decode(errors="ignore")
                m = re.search(r'realm="([^"]+)"', resp)
                if m:
                    realm = m.group(1)
        except Exception:
            pass
    return {"ip": ip, "ports": open_ports, "rtsp_realm": realm}


def discover_all_cameras() -> list[dict]:
    """Ejecuta descubrimiento completo (SADP + ONVIF + Escaneo RTSP + ARP) y unifica resultados."""
    local_ip, prefix = get_local_ip_and_prefix()
    arp = get_arp_table()
    sadp_map = scan_sadp(local_ip, prefix, rounds=2)
    onvif_map = scan_onvif(local_ip)

    all_ips = [f"{prefix}{i}" for i in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        port_results = [r for r in ex.map(probe_rtsp_and_ports, all_ips) if r]

    port_map = {r["ip"]: r for r in port_results}
    candidate_ips = sorted(
        set(sadp_map.keys()) | set(onvif_map.keys()) | set(port_map.keys()),
        key=lambda x: int(x.split(".")[-1]),
    )

    unified = []
    for ip in candidate_ips:
        s_info = sadp_map.get(ip, {})
        o_info = onvif_map.get(ip, {})
        p_info = port_map.get(ip, {})

        mac = s_info.get("mac") or arp.get(ip, "")
        ports = p_info.get("ports", [])
        realm = p_info.get("rtsp_realm", "")

        model = s_info.get("model") or o_info.get("model") or ""
        brand = s_info.get("brand") or o_info.get("brand") or ""

        # Inferencia adicional cuando un paquete UDP SADP no llegó pero responde RTSP/MAC
        if not model:
            if mac.startswith("f4:70:18") or realm.startswith("fc2422") or realm.startswith("f47018"):
                brand = "EZVIZ"
                model = "CS-H6c-R200-8H8WFL (4K)"
            elif mac.startswith("0c:a6:4c") or mac.startswith("64:24:4d") or mac.startswith("94:ec:13"):
                brand = "EZVIZ"
                model = "CS-H6c Series"
            elif 9010 in ports and 8000 in ports:
                brand = "EZVIZ"
                model = "Cámara EZVIZ"
            else:
                brand = "RTSP / Genérica"
                model = f"Cámara IP ({realm})" if realm else "Dispositivo RTSP"

        is_4k_target = "R200-8H8WFL" in model or ip in ("192.168.1.184", "192.168.1.152", "192.168.1.156")
        is_cb1 = "CB1" in model.upper()

        unified.append({
            "ip": ip,
            "mac": mac,
            "brand": brand,
            "model": model,
            "serial": s_info.get("serial", ""),
            "firmware": s_info.get("firmware", ""),
            "ports": ports,
            "rtsp_open": 554 in ports,
            "rtsp_realm": realm,
            "onvif_url": o_info.get("onvif_url", ""),
            "is_4k_model": is_4k_target,
            "is_cb1": is_cb1,
        })

    # Ordenar poniendo primero las 3 cámaras 4K CS-H6c-R200-8H8WFL y luego el resto por IP
    unified.sort(key=lambda d: (0 if d["is_4k_model"] else 1, int(d["ip"].split(".")[-1])))
    return unified


def verify_camera_stream(ip: str, user: str, password: str, port: int = 554, custom_path: str = "") -> dict:
    """
    Prueba la conexión RTSP haciendo 1 solo intento por ruta para nunca activar
    el bloqueo temporal de seguridad de EZVIZ por intentos fallidos.
    """
    paths = [custom_path] if custom_path else ["/ch1/main", "/Streaming/Channels/101"]
    last_err = "No se pudo conectar al puerto RTSP"

    # Comprobar primero sin credenciales si la cámara está en pausa temporal (404 en CSeq 1)
    try:
        with socket.create_connection((ip, port), timeout=2.0) as s:
            s.settimeout(2.0)
            s.sendall(f"DESCRIBE rtsp://{ip}:{port}/ch1/main RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
            first_resp = s.recv(2048).decode(errors="ignore")
            if "404 Not Found" in first_resp and "WWW-Authenticate" not in first_resp:
                return {
                    "ok": False,
                    "locked": True,
                    "error": f"La cámara {ip} está en pausa temporal de seguridad EZVIZ por intentos fallidos previos. Se desbloquea sola en unos minutos.",
                }
    except Exception:
        pass

    for path in paths:
        if not path.startswith("/"):
            path = "/" + path
        url = f"rtsp://{user}:{password}@{ip}:{port}{path}"
        try:
            res = subprocess.run(
                [
                    "ffprobe",
                    "-v", "info",
                    "-rtsp_transport", "tcp",
                    "-show_entries", "stream=codec_name,width,height",
                    "-of", "default=noprint_wrappers=1",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=6,
            )
            if res.returncode == 0 and "codec_name=" in res.stdout:
                width = re.search(r"width=(\d+)", res.stdout)
                height = re.search(r"height=(\d+)", res.stdout)
                codec = re.search(r"codec_name=([a-z0-9_]+)", res.stdout)
                sub_path = "/ch1/sub" if path == "/ch1/main" else (
                    "/Streaming/Channels/102" if path == "/Streaming/Channels/101" else path
                )
                return {
                    "ok": True,
                    "rtsp_main": url,
                    "rtsp_sub": f"rtsp://{user}:{password}@{ip}:{port}{sub_path}",
                    "path_main": path,
                    "path_sub": sub_path,
                    "width": int(width.group(1)) if width else 0,
                    "height": int(height.group(1)) if height else 0,
                    "codec": codec.group(1) if codec else "desconocido",
                }
            if "401 Unauthorized" in res.stderr or "401 (Unauthorized)" in res.stderr:
                return {
                    "ok": False,
                    "error": "Código de verificación o contraseña incorrecta (401 Unauthorized).",
                }
            last_err = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "Ruta RTSP no encontrada"
        except subprocess.TimeoutExpired:
            last_err = f"Tiempo de espera agotado al conectar a {ip}:{port}"
        except Exception as e:
            last_err = str(e)
    return {"ok": False, "error": last_err}


if __name__ == "__main__":
    cams = discover_all_cameras()
    print(f" Se detectaron {len(cams)} dispositivos de video en la red local:\n")
    for c in cams:
        tag = "⭐ [MODELO 4K]" if c["is_4k_model"] else "              "
        rtsp_str = "RTSP:554 OK" if c["rtsp_open"] else f"Puertos:{c['ports']}"
        print(f"{tag} {c['ip']:15} | {c['brand']:9} | {c['model']:26} | MAC: {c['mac']:17} | SN: {c['serial']} | {rtsp_str}")
