#!/usr/bin/env python3
"""
Sistema NVR Local Completo para Cámaras EZVIZ, ONVIF y RTSP:
- Visor en Vivo 4K Real (3840x2160) con Zoom Digital Interactivo (1x a 10x) y Paneo con el mouse.
- Escáner Multicapa (SADP + ONVIF + RTSP) e identificador automático por Código de Verificación.
- Gestión de múltiples cámaras (añadir, editar, eliminar, vista mosaico).
- Grabación local sin pérdida (-c:v copy) y módulo completo de Recovery de Video.
"""
import concurrent.futures
import datetime
import os
import subprocess
import time
from flask import Flask, Response, jsonify, render_template_string, request, send_file, send_from_directory

from escaner_red import discover_all_cameras, verify_camera_stream
from gestor_grabacion import (
    RECOVERED_DIR,
    load_cameras,
    load_settings,
    recorder,
    save_cameras,
    save_settings,
)

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "capturas")
os.makedirs(CAPTURES_DIR, exist_ok=True)

# Cache ligero del último escaneo de red
LAST_SCAN_CACHE: list[dict] = []

HTML_PAGE = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>NVR Local EZVIZ / ONVIF / RTSP - Visor 4K y Recovery</title>
  <style>
    :root {
      --bg: #0b1120;
      --panel: #1e293b;
      --panel2: #0f172a;
      --border: #334155;
      --accent: #38bdf8;
      --green: #22c55e;
      --red: #ef4444;
      --amber: #f59e0b;
      --text: #f8fafc;
      --muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 16px 24px;
    }
    .container { max-width: 1400px; margin: 0 auto; }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--panel);
      padding: 14px 22px;
      border-radius: 12px;
      border: 1px solid var(--border);
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .tabs {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .tab-btn {
      background: var(--panel2);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 9px 16px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.92rem;
    }
    .tab-btn.active {
      background: #0284c7;
      color: #fff;
      border-color: var(--accent);
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    .layout-live {
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 16px;
    }
    @media (max-width: 960px) {
      .layout-live { grid-template-columns: 1fr; }
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }
    .card h3 {
      font-size: 1.05rem;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .cam-item {
      background: var(--panel2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: border-color 0.15s;
    }
    .cam-item:hover, .cam-item.active {
      border-color: var(--accent);
    }
    .cam-item .title { font-weight: 600; font-size: 0.95rem; display: flex; justify-content: space-between; align-items: center; }
    .cam-item .meta { font-size: 0.8rem; color: var(--muted); margin-top: 4px; font-family: monospace; }

    /* Visor con Zoom Digital y Paneo */
    .viewport {
      background: #000;
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      position: relative;
      aspect-ratio: 16 / 9;
      user-select: none;
      cursor: grab;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .viewport:active { cursor: grabbing; }
    .viewport img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      transform-origin: center center;
      transition: transform 0.05s linear;
      pointer-events: none;
    }
    .hud-overlay {
      position: absolute;
      top: 12px;
      left: 12px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      z-index: 10;
    }
    .hud-badge {
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid var(--border);
      padding: 5px 10px;
      border-radius: 6px;
      font-size: 0.82rem;
      font-family: monospace;
      color: var(--accent);
    }
    .hud-rec {
      background: rgba(239, 68, 68, 0.9);
      color: #fff;
      font-weight: 700;
      animation: pulse 1.2s infinite;
    }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
      align-items: center;
    }
    button, .btn {
      background: #334155;
      color: var(--text);
      border: 1px solid #475569;
      padding: 8px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.88rem;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    button:hover, .btn:hover { background: #475569; }
    button.primary { background: #0284c7; border-color: var(--accent); }
    button.primary:hover { background: #0369a1; }
    button.success { background: #16a34a; border-color: var(--green); }
    button.danger { background: #dc2626; border-color: var(--red); }

    input, select {
      background: var(--panel2);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 0.9rem;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .form-group label {
      display: block;
      font-size: 0.8rem;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .form-group input, .form-group select { width: 100%; }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
    }
    th { color: var(--muted); font-size: 0.78rem; text-transform: uppercase; }
    tr.highlight-4k { background: rgba(56, 189, 248, 0.08); }
    .tag {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 99px;
      font-size: 0.75rem;
      font-weight: 600;
    }
    .tag-4k { background: rgba(56, 189, 248, 0.2); color: var(--accent); border: 1px solid var(--accent); }
    .tag-ok { background: rgba(34, 197, 94, 0.2); color: var(--green); }
    .tag-warn { background: rgba(245, 158, 11, 0.2); color: var(--amber); }

    #toast {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #0284c7;
      color: #fff;
      padding: 12px 20px;
      border-radius: 8px;
      font-weight: 600;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
      display: none;
      z-index: 9999;
    }
    .grid-mosaic {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 14px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h2>🛡️ Sistema NVR Local EZVIZ / ONVIF / RTSP (4K + Zoom + Recovery)</h2>
        <p style="color: var(--muted); font-size: 0.85rem; margin-top: 3px;">
          Visualización 4K nativa (3840×2160) con Zoom interactivo, descubrimiento multicapa (SADP/ONVIF/RTSP) y grabación/recuperación local
        </p>
      </div>
      <div class="tabs">
        <button class="tab-btn active" onclick="showTab('live', this)">🎥 Visor 4K + Zoom</button>
        <button class="tab-btn" onclick="showTab('mosaic', this)">🧱 Mosaico Multi-Cámara</button>
        <button class="tab-btn" onclick="showTab('discover', this)">🔍 Descubrir / Añadir Cámaras</button>
        <button class="tab-btn" onclick="showTab('recordings', this)">💾 Grabaciones y Recovery</button>
      </div>
    </header>

    <!-- TAB 1: VISOR 4K + ZOOM -->
    <div id="tab-live" class="tab-content active">
      <div class="layout-live">
        <div>
          <div class="card">
            <h3>
              <span>📹 Mis Cámaras</span>
              <button onclick="showTab('discover', document.querySelectorAll('.tab-btn')[2])" style="padding:4px 8px; font-size:0.78rem;">+ Añadir</button>
            </h3>
            <div id="camera-list"></div>
          </div>

          <div class="card">
            <h3>🔍 Controles de Zoom 4K</h3>
            <p style="font-size: 0.82rem; color: var(--muted); margin-bottom: 10px;">
              Usa la <b>rueda del mouse</b> sobre el video para hacer zoom (hasta 10x) y <b>arrastra con clic izquierdo</b> para moverte por la imagen 4K.
            </p>
            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;">
              <button onclick="setZoom(1)">1x (100%)</button>
              <button onclick="setZoom(2)">2x</button>
              <button onclick="setZoom(3)">3x</button>
              <button onclick="setZoom(4)">4x</button>
              <button onclick="setZoom(6)">6x</button>
              <button onclick="setZoom(8)">8x</button>
            </div>
            <label style="font-size:0.8rem; color:var(--muted);">Nivel de Zoom: <b id="zoom-label">1.0x</b></label>
            <input type="range" id="zoom-slider" min="1" max="10" step="0.2" value="1" style="width:100%; margin-top:6px;" oninput="setZoom(parseFloat(this.value))">
          </div>
        </div>

        <div>
          <div class="viewport" id="video-viewport">
            <div class="hud-overlay">
              <span class="hud-badge" id="hud-cam-name">Cargando...</span>
              <span class="hud-badge" id="hud-res">4K Ultra HD (3840×2160)</span>
              <span class="hud-badge" id="hud-zoom">Zoom: 1.0x</span>
              <span class="hud-badge hud-rec" id="hud-rec" style="display:none;">● REC 4K</span>
            </div>
            <img id="live-img" src="" alt="Selecciona una cámara" />
          </div>

          <div class="toolbar">
            <button class="primary" onclick="changeQuality('main')">✨ Calidad 4K Real (3840×2160)</button>
            <button onclick="changeQuality('sub')">⚡ Modo Fluido HD (1280×720)</button>
            <button onclick="toggleFullscreen()">⛶ Pantalla Completa</button>
            <button onclick="takeSnapshot()">📸 Captura 4K</button>
            <button id="btn-record" class="success" onclick="toggleRecordCurrent()">⏺ Iniciar Grabación 24/7</button>
            <button onclick="openNativeWindow(1)">🖥️ Ventana Nativa 4K (Audio)</button>
            <button onclick="openNativeWindow(2)">🔍 Ventana Nativa Zoom 2x</button>
            <button onclick="openNativeWindow(4)">🔍 Ventana Nativa Zoom 4x</button>
          </div>

          <!-- PANEL DIRECTO EN PANTALLA PRINCIPAL: CARPETA 24/7 Y CAPACIDAD MÍNIMO 500 GB -->
          <div class="card" style="margin-top: 16px; border: 2px solid var(--accent);">
            <h3>
              <span>💾 Configuración de Grabación 24/7: Carpeta y Límite de Capacidad (Mínimo 500 GB)</span>
              <div style="display:flex; gap:8px;">
                <button class="success" onclick="toggleAll247('start')">⏺ Grabar 24/7 Todas</button>
                <button class="danger" onclick="toggleAll247('stop')">⏹ Detener Todas</button>
              </div>
            </h3>
            <p style="font-size: 0.85rem; color: var(--muted); margin-bottom: 10px;">
              Indica aquí en qué carpeta se guardará la grabación 24/7 en 4K y cuál es la <b>capacidad máxima permitida (mínimo 500 GB, ej. 1000 GB = 1 TB)</b>. Cuando la carpeta llene esa capacidad, <b>se irá borrando automáticamente lo más antiguo</b>.
            </p>

            <div style="background: var(--panel2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-bottom: 12px;">
              <div style="display:flex; justify-content:space-between; font-size:0.86rem; margin-bottom:6px; flex-wrap:wrap; gap:8px;">
                <span>📊 Espacio Ocupado en Carpeta: <b id="main-stat-used" style="color:var(--accent);">0 GB</b> de <b id="main-stat-max">1000 GB</b> (<span id="main-stat-pct">0%</span>)</span>
                <span>💽 Disco Libre: <b id="main-stat-free">- GB</b> | 🗑️ Videos antiguos borrados por límite: <b id="main-stat-deleted">0</b></span>
              </div>
              <div style="width:100%; height:10px; background:#1e293b; border-radius:99px; overflow:hidden;">
                <div id="main-stat-bar" style="width:0%; height:100%; background:linear-gradient(90deg, #22c55e, #38bdf8); transition:width 0.3s;"></div>
              </div>
            </div>

            <div class="form-grid">
              <div class="form-group" style="grid-column: span 2;">
                <label>📁 Ruta de la Carpeta para Grabación 24/7</label>
                <input type="text" id="main-storage-dir" placeholder="/mnt/disco1tb/grabaciones">
              </div>
              <div class="form-group">
                <label>⚖️ Capacidad Límite de la Carpeta en GB (Mínimo 500 GB)</label>
                <input type="number" id="main-max-gb" min="500" step="50" value="1000">
                <div style="display:flex; gap:4px; margin-top:6px; flex-wrap:wrap;">
                  <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="setQuotaPreset(500)">500 GB (Mín)</button>
                  <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="setQuotaPreset(750)">750 GB</button>
                  <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="setQuotaPreset(1000)">1000 GB (1 TB)</button>
                  <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="setQuotaPreset(2000)">2000 GB (2 TB)</button>
                </div>
              </div>
              <div class="form-group">
                <label>⏱️ Corte de Archivo (segundos)</label>
                <input type="number" id="main-seg-sec" min="60" value="300">
              </div>
            </div>
            <button class="primary" onclick="saveSettingsFromMain()">💾 Aplicar Carpeta y Límite de Capacidad (Mín. 500 GB)</button>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: MOSAICO MULTI-CÁMARA -->
    <div id="tab-mosaic" class="tab-content">
      <div class="card">
        <h3>
          <span>🧱 Vista Simultánea de Cámaras Configuradas</span>
          <button onclick="renderMosaic()">🔄 Refrescar Mosaico</button>
        </h3>
        <div id="mosaic-container" class="grid-mosaic"></div>
      </div>
    </div>

    <!-- TAB 3: DESCUBRIR Y AÑADIR CÁMARAS -->
    <div id="tab-discover" class="tab-content">
      <div class="card" style="border-color: var(--accent);">
        <h3>🔑 Identificador Automático por Código de Verificación EZVIZ</h3>
        <p style="font-size: 0.88rem; color: var(--muted); margin-bottom: 12px;">
          ¿Tienes el código de verificación (6 letras) de las otras cámaras pero no sabes cuál IP les corresponde? Escríbelo aquí y el sistema probará automáticamente las cámaras de tu red hasta encontrar la correcta y añadirla:
        </p>
        <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end;">
          <div class="form-group" style="flex: 1; min-width: 200px;">
            <label>Nombre para la Cámara (ej. Cámara 4K #2)</label>
            <input type="text" id="probe-name" placeholder="Cámara EZVIZ 4K #2">
          </div>
          <div class="form-group" style="flex: 1; min-width: 180px;">
            <label>Código de Verificación / Contraseña RTSP</label>
            <input type="text" id="probe-code" placeholder="Ej: ABCDEF">
          </div>
          <div class="form-group" style="min-width: 220px;">
            <label>Dónde buscar</label>
            <select id="probe-scope">
              <option value="4k">Solo en las 3 cámaras 4K (CS-H6c-R200-8H8WFL: .152, .156, .184)</option>
              <option value="all">En todas las cámaras de la red (192.168.1.0/24)</option>
            </select>
          </div>
          <button class="primary" onclick="findCameraByCode()">🚀 Buscar IP por Código y Añadir</button>
        </div>
      </div>

      <div class="card">
        <h3>
          <span>📡 Cámaras Detectadas en tu Red Local (SADP / ONVIF / RTSP)</span>
          <button class="primary" onclick="scanNetwork(true)">🔍 Re-escanear Red Ahora</button>
        </h3>
        <p style="font-size: 0.85rem; color: var(--muted); margin-bottom: 12px;">
          Las filas resaltadas en azul son tus <b>3 cámaras del mismo modelo 4K (<code>CS-H6c-R200-8H8WFL</code>)</b>. Si enciendes tu cámara <b><code>CS-CB1</code></b>, dale a "Re-escanear Red Ahora" y aparecerá aquí automáticamente.
        </p>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Estado / Categoría</th>
                <th>IP</th>
                <th>Marca</th>
                <th>Modelo Exacto (SADP/ONVIF)</th>
                <th>Número de Serie (SN)</th>
                <th>Dirección MAC</th>
                <th>Puertos</th>
                <th>Acción Rápida</th>
              </tr>
            </thead>
            <tbody id="discovered-tbody">
              <tr><td colspan="8">Cargando dispositivos detectados...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h3>➕ Añadir Cámara Manualmente (EZVIZ / ONVIF / RTSP de cualquier marca)</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>Nombre de la Cámara</label>
            <input type="text" id="add-name" placeholder="Ej. Entrada Principal">
          </div>
          <div class="form-group">
            <label>Dirección IP</label>
            <input type="text" id="add-ip" placeholder="192.168.1.152">
          </div>
          <div class="form-group">
            <label>Marca / Protocolo</label>
            <select id="add-brand">
              <option value="EZVIZ">EZVIZ (RTSP / SADP)</option>
              <option value="Hikvision">Hikvision</option>
              <option value="ONVIF">ONVIF / Otra Marca</option>
              <option value="RTSP">RTSP Genérica</option>
            </select>
          </div>
          <div class="form-group">
            <label>Usuario RTSP</label>
            <input type="text" id="add-user" value="admin">
          </div>
          <div class="form-group">
            <label>Código Verificación / Contraseña</label>
            <input type="text" id="add-pass" placeholder="Código de 6 letras o clave">
          </div>
          <div class="form-group">
            <label>Puerto RTSP</label>
            <input type="number" id="add-port" value="554">
          </div>
          <div class="form-group">
            <label>Ruta RTSP (opcional, auto-detecta)</label>
            <input type="text" id="add-path" placeholder="/ch1/main">
          </div>
        </div>
        <button class="primary" onclick="addCameraManual()">✅ Probar Conexión RTSP y Guardar Cámara</button>
      </div>
    </div>

    <!-- TAB 4: GRABACIONES LOCALES 24/7, CUOTA 1TB Y RECOVERY DE VIDEO -->
    <div id="tab-recordings" class="tab-content">
      <div class="card" style="border-color: var(--accent);">
        <h3>
          <span>⚙️ Grabación Continua 24/7 y Rotación Automática de Disco (FIFO)</span>
          <div style="display:flex; gap:8px;">
            <button class="success" onclick="toggleAll247('start')">⏺ Activar 24/7 en Todas</button>
            <button class="danger" onclick="toggleAll247('stop')">⏹ Detener Todas</button>
          </div>
        </h3>
        <p style="font-size: 0.85rem; color: var(--muted); margin-bottom: 12px;">
          El servidor graba 24/7 en calidad 4K sin recodificar (<code>-c:v copy</code>) y monitorea cada 30 segundos el tamaño de la carpeta. Cuando alcanza el límite configurado (mínimo <b>500 GB</b>, ej. <b>1000 GB = 1 TB</b>), <b>elimina automáticamente las grabaciones más antiguas</b> para nunca detener la grabación.
        </p>

        <!-- Barra de estado de almacenamiento -->
        <div style="background: var(--panel2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 14px;">
          <div style="display:flex; justify-content:space-between; font-size:0.88rem; margin-bottom:6px; flex-wrap:wrap; gap:8px;">
            <span>📊 Uso de Carpeta NVR: <b id="stat-used" style="color:var(--accent);">0 GB</b> / <b id="stat-max">1000 GB</b> (<span id="stat-pct">0%</span>)</span>
            <span>💽 Disco Físico Libre: <b id="stat-free">- GB</b> | 🗑️ Antiguos auto-eliminados: <b id="stat-deleted">0</b></span>
          </div>
          <div style="width:100%; height:10px; background:#1e293b; border-radius:99px; overflow:hidden;">
            <div id="stat-bar" style="width:0%; height:100%; background:linear-gradient(90deg, #22c55e, #38bdf8); transition:width 0.3s;"></div>
          </div>
        </div>

        <div class="form-grid">
          <div class="form-group" style="grid-column: span 2;">
            <label>Carpeta Local de Almacenamiento 24/7 (en Docker: /grabaciones)</label>
            <input type="text" id="set-storage-dir" value="">
          </div>
          <div class="form-group">
            <label>Tamaño Máximo de Carpeta en GB (Mínimo 500 GB)</label>
            <input type="number" id="set-max-gb" min="500" step="50" value="1000">
            <div style="display:flex; gap:4px; margin-top:6px; flex-wrap:wrap;">
              <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="document.getElementById('set-max-gb').value=500">500 GB</button>
              <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="document.getElementById('set-max-gb').value=750">750 GB</button>
              <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="document.getElementById('set-max-gb').value=1000">1000 GB (1 TB)</button>
              <button type="button" style="padding:3px 7px; font-size:0.75rem;" onclick="document.getElementById('set-max-gb').value=2000">2000 GB (2 TB)</button>
            </div>
          </div>
          <div class="form-group">
            <label>Duración por Segmento (segundos)</label>
            <input type="number" id="set-seg-sec" min="60" value="300">
          </div>
          <div class="form-group">
            <label>Calidad de Grabación 24/7</label>
            <select id="set-rec-stream">
              <option value="main">4K Original sin pérdida (-c:v copy)</option>
              <option value="sub">HD 720p Ahorro de espacio</option>
            </select>
          </div>
        </div>
        <button class="primary" onclick="saveSettings()">💾 Guardar Configuración 24/7 y Límite de Disco</button>
      </div>

      <div class="card" style="border-color: var(--amber);">
        <h3>🛠️ Recovery y Unión de Video por Rango de Horario</h3>
        <p style="font-size: 0.85rem; color: var(--muted); margin-bottom: 12px;">
          Selecciona una cámara, fecha y rango de horas para recuperar, reparar índices dañados y unir todos los segmentos en un solo archivo MP4 continuo:
        </p>
        <div class="form-grid">
          <div class="form-group">
            <label>Cámara</label>
            <select id="rec-cam-select"></select>
          </div>
          <div class="form-group">
            <label>Fecha (YYYY-MM-DD)</label>
            <input type="date" id="rec-date">
          </div>
          <div class="form-group">
            <label>Hora Inicio (HH:MM)</label>
            <input type="time" id="rec-start" value="00:00">
          </div>
          <div class="form-group">
            <label>Hora Fin (HH:MM)</label>
            <input type="time" id="rec-end" value="23:59">
          </div>
        </div>
        <button class="primary" onclick="recoverRange()">🔧 Recuperar y Unir Rango de Video</button>
        <div id="recovery-result" style="margin-top: 12px; font-size: 0.9rem; color: var(--green);"></div>
      </div>

      <div class="card">
        <h3>
          <span>🎞️ Reproductor de Grabaciones y Segmentos Locales</span>
          <button onclick="loadRecordings()">🔄 Actualizar Lista</button>
        </h3>
        <div id="player-box" style="display:none; margin-bottom: 16px; background:#000; padding:12px; border-radius:10px;">
          <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
            <b id="playing-title" style="color:var(--accent);">Reproduciendo...</b>
            <button onclick="document.getElementById('player-box').style.display='none'">✖ Cerrar</button>
          </div>
          <video id="rec-video" controls style="width:100%; max-height:480px; background:#000;"></video>
        </div>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Cámara</th>
                <th>Fecha</th>
                <th>Hora</th>
                <th>Archivo</th>
                <th>Tamaño</th>
                <th>Acciones (Reproducir / Recovery / Descargar)</th>
              </tr>
            </thead>
            <tbody id="recordings-tbody">
              <tr><td colspan="6">Cargando grabaciones...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <div id="toast"></div>

  <script>
    let cameras = [];
    let currentCam = null;
    let currentMode = 'main'; // Empezar en 4K real por defecto
    let zoomLevel = 1.0;
    let panX = 0, panY = 0;
    let isDragging = false, startX = 0, startY = 0;

    function toast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 4500);
    }

    function showTab(name, btn) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      if (btn) btn.classList.add('active');
      if (name === 'mosaic') renderMosaic();
      if (name === 'discover') scanNetwork(false);
      if (name === 'recordings') loadRecordings();
    }

    // Zoom & Pan Interactivo sobre el stream 4K
    const viewport = document.getElementById('video-viewport');
    const liveImg = document.getElementById('live-img');

    function updateTransform() {
      if (zoomLevel <= 1.0) { panX = 0; panY = 0; }
      liveImg.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomLevel})`;
      document.getElementById('zoom-label').textContent = zoomLevel.toFixed(1) + 'x';
      document.getElementById('hud-zoom').textContent = 'Zoom: ' + zoomLevel.toFixed(1) + 'x';
      document.getElementById('zoom-slider').value = zoomLevel;
    }

    function setZoom(z) {
      zoomLevel = Math.max(1.0, Math.min(10.0, z));
      updateTransform();
    }

    viewport.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.35 : -0.35;
      setZoom(zoomLevel + delta);
    }, { passive: false });

    viewport.addEventListener('mousedown', (e) => {
      if (zoomLevel <= 1.0) return;
      isDragging = true;
      startX = e.clientX - panX;
      startY = e.clientY - panY;
    });
    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      panX = e.clientX - startX;
      panY = e.clientY - startY;
      updateTransform();
    });
    window.addEventListener('mouseup', () => { isDragging = false; });

    async function loadCameras() {
      const res = await fetch('/api/cameras');
      const data = await res.json();
      cameras = data.cameras;
      const list = document.getElementById('camera-list');
      const recSel = document.getElementById('rec-cam-select');
      list.innerHTML = '';
      recSel.innerHTML = '<option value="">Todas las cámaras</option>';

      cameras.forEach(c => {
        recSel.innerHTML += `<option value="${c.id}">${c.name} (${c.ip})</option>`;
        const div = document.createElement('div');
        div.className = 'cam-item' + (currentCam && currentCam.id === c.id ? ' active' : '');
        div.onclick = () => selectCamera(c);
        div.innerHTML = `
          <div class="title">
            <span>${c.name}</span>
            <span class="tag ${c.recording ? 'tag-warn' : 'tag-ok'}">${c.recording ? '● REC' : c.password}</span>
          </div>
          <div class="meta" style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
            <span>${c.ip} | SN: ${c.serial || '-'}</span>
            <button onclick="event.stopPropagation(); editCameraPassword('${c.id}', '${c.name}', '${c.password}')" style="padding:2px 7px; font-size:0.75rem;">🔑 Clave</button>
          </div>
        `;
        list.appendChild(div);
      });

      if (!currentCam && cameras.length > 0) {
        selectCamera(cameras[0]);
      } else if (currentCam) {
        const updated = cameras.find(x => x.id === currentCam.id);
        if (updated) updateRecButton(updated);
      }
    }

    async function editCameraPassword(camId, camName, currentPass) {
      const newPass = prompt(`Ingresa el código de verificación o contraseña RTSP para ${camName}:`, currentPass || '');
      if (!newPass) return;
      const res = await fetch('/api/cameras/update_password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id: camId, password: newPass.trim() })
      });
      const data = await res.json();
      if (data.ok) {
        toast('✅ Clave actualizada para ' + camName);
        await loadCameras();
        if (currentCam && currentCam.id === camId) selectCamera(data.camera);
      } else {
        toast('❌ ' + data.error);
      }
    }

    function selectCamera(cam) {
      currentCam = cam;
      setZoom(1.0);
      document.getElementById('hud-cam-name').textContent = `${cam.name} (${cam.ip})`;
      changeQuality(currentMode);
      updateRecButton(cam);
      loadCameras();
    }

    function updateRecButton(cam) {
      const btn = document.getElementById('btn-record');
      const badge = document.getElementById('hud-rec');
      if (cam.recording) {
        btn.textContent = '⏹ Detener Grabación Local';
        btn.className = 'danger';
        badge.style.display = 'inline-block';
      } else {
        btn.textContent = '⏺ Iniciar Grabación Local';
        btn.className = 'success';
        badge.style.display = 'none';
      }
    }

    function changeQuality(mode) {
      if (!currentCam) return;
      currentMode = mode;
      const resBadge = document.getElementById('hud-res');
      if (mode === 'main') {
        resBadge.textContent = `4K Nativo (${currentCam.width || 3840}×${currentCam.height || 2160})`;
      } else {
        resBadge.textContent = 'HD Fluido (1280×720)';
      }
      liveImg.src = `/api/stream/${currentCam.id}?mode=${mode}&t=${Date.now()}`;
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        viewport.requestFullscreen();
      } else {
        document.exitFullscreen();
      }
    }

    async function takeSnapshot() {
      if (!currentCam) return;
      toast('📸 Capturando fotograma en resolución 4K nativa (3840×2160)...');
      const res = await fetch(`/api/snapshot/${currentCam.id}`, { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        toast('✅ Captura 4K guardada: ' + data.filename);
        window.open('/capturas/' + data.filename, '_blank');
      } else {
        toast('❌ Error: ' + data.error);
      }
    }

    async function toggleRecordCurrent() {
      if (!currentCam) return;
      const action = currentCam.recording ? 'stop' : 'start';
      const res = await fetch(`/api/record/${currentCam.id}/${action}`, { method: 'POST' });
      const data = await res.json();
      toast(data.message);
      await loadCameras();
    }

    async function openNativeWindow(zoom) {
      if (!currentCam) return;
      toast(`🖥️ Abriendo ventana nativa 4K (Zoom ${zoom}x)...`);
      await fetch(`/api/open_native/${currentCam.id}?mode=main&zoom=${zoom}`, { method: 'POST' });
    }

    function renderMosaic() {
      const box = document.getElementById('mosaic-container');
      box.innerHTML = '';
      cameras.forEach(c => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <h3><span>${c.name} (${c.ip})</span> <span class="tag tag-4k">${c.model}</span></h3>
          <div class="viewport" style="cursor:pointer;" onclick="selectCameraById('${c.id}')">
            <img src="/api/stream/${c.id}?mode=sub&t=${Date.now()}" />
          </div>
        `;
        box.appendChild(card);
      });
    }

    function selectCameraById(cid) {
      const c = cameras.find(x => x.id === cid);
      if (c) {
        showTab('live', document.querySelectorAll('.tab-btn')[0]);
        selectCamera(c);
      }
    }

    async function scanNetwork(force) {
      const tbody = document.getElementById('discovered-tbody');
      if (force) {
        tbody.innerHTML = '<tr><td colspan="8">🔍 Escaneando toda la red 192.168.1.0/24 por SADP, ONVIF y RTSP...</td></tr>';
      }
      const res = await fetch('/api/discover?force=' + (force ? '1' : '0'));
      const data = await res.json();
      tbody.innerHTML = '';
      const addedIps = new Set(cameras.map(c => c.ip));

      data.devices.forEach(d => {
        const isAdded = addedIps.has(d.ip);
        const tr = document.createElement('tr');
        if (d.is_4k_model) tr.className = 'highlight-4k';

        let badge = '<span class="tag">Cámara IP</span>';
        if (d.is_4k_model) badge = '<span class="tag tag-4k">⭐ Modelo 4K (CS-H6c-R200)</span>';
        else if (d.is_cb1) badge = '<span class="tag tag-warn">🔋 Modelo CS-CB1</span>';

        tr.innerHTML = `
          <td>${badge} ${isAdded ? '<span class="tag tag-ok">✔ Añadida</span>' : ''}</td>
          <td style="font-family:monospace; font-weight:700;">${d.ip}</td>
          <td>${d.brand}</td>
          <td style="font-family:monospace;">${d.model}</td>
          <td style="font-family:monospace; font-size:0.78rem;">${d.serial || '-'}</td>
          <td style="font-family:monospace;">${d.mac || '-'}</td>
          <td>${d.ports.join(', ')}</td>
          <td>
            <button onclick="prefillAdd('${d.ip}', '${d.brand}', '${d.model}')">➕ Configurar</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function prefillAdd(ip, brand, model) {
      document.getElementById('add-ip').value = ip;
      document.getElementById('add-name').value = `${brand} ${model} (${ip.split('.').pop()})`;
      document.getElementById('add-pass').focus();
      toast(`IP ${ip} cargada en el formulario inferior. Ingresa su código de verificación.`);
    }

    async function findCameraByCode() {
      const code = document.getElementById('probe-code').value.trim();
      const name = document.getElementById('probe-name').value.trim();
      const scope = document.getElementById('probe-scope').value;
      if (!code) { toast('⚠️ Ingresa el código de verificación de la cámara'); return; }
      toast(`🔍 Probando el código ${code} en las cámaras de la red...`);
      const res = await fetch('/api/find_by_code', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ code, name, scope })
      });
      const data = await res.json();
      if (data.ok) {
        toast(`✅ ¡Encontrada en ${data.camera.ip}! Añadida como "${data.camera.name}"`);
        await loadCameras();
        await scanNetwork(false);
      } else {
        toast('❌ ' + data.error);
      }
    }

    async function addCameraManual() {
      const payload = {
        name: document.getElementById('add-name').value.trim(),
        ip: document.getElementById('add-ip').value.trim(),
        brand: document.getElementById('add-brand').value,
        user: document.getElementById('add-user').value.trim() || 'admin',
        password: document.getElementById('add-pass').value.trim(),
        port: parseInt(document.getElementById('add-port').value || '554'),
        path: document.getElementById('add-path').value.trim()
      };
      if (!payload.ip || !payload.password) {
        toast('⚠️ Completa la IP y el código/contraseña');
        return;
      }
      toast(`🔌 Verificando stream RTSP en ${payload.ip}...`);
      const res = await fetch('/api/cameras/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.ok) {
        toast(`✅ Cámara añadida (${data.camera.width}x${data.camera.height})`);
        await loadCameras();
        showTab('live', document.querySelectorAll('.tab-btn')[0]);
        selectCamera(data.camera);
      } else {
        toast('❌ Error: ' + data.error);
      }
    }

    function setQuotaPreset(val) {
      document.getElementById('main-max-gb').value = val;
      document.getElementById('set-max-gb').value = val;
    }

    async function loadSettings() {
      const res = await fetch('/api/settings');
      const s = await res.json();
      document.getElementById('set-storage-dir').value = s.storage_dir;
      document.getElementById('set-max-gb').value = s.max_storage_gb || 1000;
      document.getElementById('set-seg-sec').value = s.segment_seconds;
      document.getElementById('set-rec-stream').value = s.record_stream;

      document.getElementById('main-storage-dir').value = s.storage_dir;
      document.getElementById('main-max-gb').value = s.max_storage_gb || 1000;
      document.getElementById('main-seg-sec').value = s.segment_seconds;

      if (!document.getElementById('rec-date').value) {
        document.getElementById('rec-date').value = new Date().toISOString().slice(0, 10);
      }
      await loadStorageStats();
    }

    async function loadStorageStats() {
      const res = await fetch('/api/storage_status');
      const st = await res.json();
      document.getElementById('stat-used').textContent = st.used_gb + ' GB';
      document.getElementById('stat-max').textContent = st.max_storage_gb + ' GB';
      document.getElementById('stat-pct').textContent = st.usage_percent + '%';
      document.getElementById('stat-free').textContent = st.disk_free_gb + ' GB (de ' + st.disk_total_gb + ' GB)';
      document.getElementById('stat-deleted').textContent = st.deleted_segments_total + ' (' + st.deleted_gb_total + ' GB liberados)';
      document.getElementById('stat-bar').style.width = st.usage_percent + '%';

      document.getElementById('main-stat-used').textContent = st.used_gb + ' GB';
      document.getElementById('main-stat-max').textContent = st.max_storage_gb + ' GB';
      document.getElementById('main-stat-pct').textContent = st.usage_percent + '%';
      document.getElementById('main-stat-free').textContent = st.disk_free_gb + ' GB (de ' + st.disk_total_gb + ' GB)';
      document.getElementById('main-stat-deleted').textContent = st.deleted_segments_total + ' (' + st.deleted_gb_total + ' GB)';
      document.getElementById('main-stat-bar').style.width = st.usage_percent + '%';
    }

    async function saveSettingsFromMain() {
      document.getElementById('set-storage-dir').value = document.getElementById('main-storage-dir').value;
      document.getElementById('set-max-gb').value = document.getElementById('main-max-gb').value;
      document.getElementById('set-seg-sec').value = document.getElementById('main-seg-sec').value;
      await saveSettings();
    }

    async function saveSettings() {
      const maxGb = parseFloat(document.getElementById('set-max-gb').value || '1000');
      if (maxGb < 500) {
        toast('⚠️ El límite de la carpeta no puede ser menor a 500 GB.');
        document.getElementById('set-max-gb').value = 500;
        return;
      }
      const payload = {
        storage_dir: document.getElementById('set-storage-dir').value.trim(),
        max_storage_gb: maxGb,
        segment_seconds: parseInt(document.getElementById('set-seg-sec').value || '300'),
        record_stream: document.getElementById('set-rec-stream').value
      };
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.ok) {
        toast(`✅ Guardado: Límite automático fijado en ${data.settings.max_storage_gb} GB`);
        await loadStorageStats();
      } else {
        toast('❌ ' + data.error);
      }
    }

    async function toggleAll247(action) {
      const res = await fetch('/api/record_all/' + action, { method: 'POST' });
      const data = await res.json();
      toast(data.message);
      await loadCameras();
    }

    async function loadRecordings() {
      await loadSettings();
      const res = await fetch('/api/recordings');
      const data = await res.json();
      const tbody = document.getElementById('recordings-tbody');
      tbody.innerHTML = '';
      if (!data.recordings.length) {
        tbody.innerHTML = '<tr><td colspan="6">Aún no hay grabaciones. Pulsa "⏺ Iniciar Grabación Local" en el Visor para grabar en 4K.</td></tr>';
        return;
      }
      data.recordings.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><b>${r.cam_name}</b></td>
          <td>${r.date}</td>
          <td style="font-family:monospace;">${r.time}</td>
          <td style="font-family:monospace; font-size:0.8rem;">${r.filename}</td>
          <td>${r.size_mb} MB</td>
          <td style="display:flex; gap:6px; flex-wrap:wrap;">
            <button class="primary" onclick="playRecording('${r.rel_path}', '${r.cam_name} - ${r.date} ${r.time}')">▶ Ver en Web</button>
            <button onclick="openRecordingNative('${r.rel_path}')">🖥️ Ver 4K Nativo</button>
            <button onclick="recoverSingleFile('${r.rel_path}')">🛠️ Recovery / Reparar</button>
            <a class="btn" href="/api/recordings/download/${r.rel_path}" download>⬇ Descargar MP4</a>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function playRecording(relPath, title) {
      const box = document.getElementById('player-box');
      const vid = document.getElementById('rec-video');
      document.getElementById('playing-title').textContent = title;
      box.style.display = 'block';
      vid.src = '/api/recordings/stream/' + relPath;
      vid.play();
    }

    async function openRecordingNative(relPath) {
      toast('🖥️ Abriendo grabación 4K en reproductor de escritorio...');
      await fetch('/api/recordings/open_native', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ rel_path: relPath })
      });
    }

    async function recoverSingleFile(relPath) {
      toast('🛠️ Ejecutando Recovery y reconstrucción de índice MP4...');
      const res = await fetch('/api/recordings/recover_file', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ rel_path: relPath })
      });
      const data = await res.json();
      if (data.ok) {
        toast('✅ ' + data.message);
        window.open('/recuperados/' + data.filename, '_blank');
      } else {
        toast('❌ Error: ' + data.error);
      }
    }

    async function recoverRange() {
      const cam_id = document.getElementById('rec-cam-select').value || (currentCam ? currentCam.id : '');
      const date_str = document.getElementById('rec-date').value;
      const start_time = document.getElementById('rec-start').value;
      const end_time = document.getElementById('rec-end').value;
      if (!cam_id) { toast('⚠️ Selecciona una cámara específica'); return; }
      toast('🔧 Uniendo y recuperando segmentos del rango horario...');
      const res = await fetch('/api/recordings/recover_range', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ cam_id, date_str, start_time, end_time })
      });
      const data = await res.json();
      const box = document.getElementById('recovery-result');
      if (data.ok) {
        box.innerHTML = `✅ ${data.message} — <a href="/recuperados/${data.filename}" download style="color:var(--accent); font-weight:700;">⬇ Descargar ${data.filename}</a>`;
        toast('✅ Clip recuperado con éxito');
      } else {
        box.innerHTML = `<span style="color:var(--red);">❌ ${data.error}</span>`;
      }
    }

    loadCameras();
    loadSettings();
    setInterval(loadStorageStats, 15000);
  </script>
</body>
</html>
"""


@app.after_request
def add_no_cache_headers(response):
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


def mjpeg_stream_generator(rtsp_url: str, native_4k: bool = True):
    """
    Genera stream MJPEG desde RTSP.
    Cuando native_4k=True, NO reduce la resolución (envía los 3840x2160 píxeles completos)
    para que el Zoom Digital en el navegador tenga nitidez 4K real.
    """
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-i", rtsp_url,
    ]
    if native_4k:
        cmd += ["-r", "10", "-q:v", "4"]
    else:
        cmd += ["-vf", "scale=1280:-1", "-r", "15", "-q:v", "6"]

    cmd += ["-f", "mpjpeg", "-boundary_tag", "frame", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    try:
        while True:
            chunk = proc.stdout.read(8192)
            if not chunk:
                break
            yield chunk
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/api/cameras")
def api_cameras():
    cams = load_cameras()
    for c in cams:
        c["recording"] = recorder.is_recording(c["id"])
    return jsonify({"cameras": cams})


@app.route("/api/stream/<cam_id>")
def api_stream(cam_id: str):
    mode = request.args.get("mode", "main")
    cams = {c["id"]: c for c in load_cameras()}
    if cam_id not in cams:
        return "Cámara no encontrada", 404
    cam = cams[cam_id]
    if mode == "main":
        return Response(
            mjpeg_stream_generator(cam["rtsp_main"], native_4k=True),
            mimetype="multipart/x-mixed-replace;boundary=frame",
        )
    return Response(
        mjpeg_stream_generator(cam["rtsp_sub"], native_4k=False),
        mimetype="multipart/x-mixed-replace;boundary=frame",
    )


@app.route("/api/snapshot/<cam_id>", methods=["POST"])
def api_snapshot(cam_id: str):
    cams = {c["id"]: c for c in load_cameras()}
    if cam_id not in cams:
        return jsonify({"ok": False, "error": "Cámara no encontrada"}), 404
    cam = cams[cam_id]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{cam_id}_4K_{ts}.jpg"
    filepath = os.path.join(CAPTURES_DIR, filename)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-loglevel", "error",
                "-rtsp_transport", "tcp",
                "-i", cam["rtsp_main"],
                "-frames:v", "1",
                "-q:v", "2",
                "-update", "1",
                filepath,
            ],
            check=True,
            timeout=8,
        )
        return jsonify({"ok": True, "filename": filename, "path": filepath})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/open_native/<cam_id>", methods=["POST"])
def api_open_native(cam_id: str):
    mode = request.args.get("mode", "main")
    zoom = request.args.get("zoom", "1")
    cams = {c["id"]: c for c in load_cameras()}
    if cam_id not in cams:
        return jsonify({"ok": False, "error": "Cámara no encontrada"}), 404
    cam = cams[cam_id]
    url = cam["rtsp_main"] if mode == "main" else cam["rtsp_sub"]
    script = os.path.join(BASE_DIR, "ver_camara.sh")
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0.0")
    subprocess.Popen([script, cam["name"], url, str(zoom)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return jsonify({"ok": True})


@app.route("/api/discover")
def api_discover():
    global LAST_SCAN_CACHE
    force = request.args.get("force", "0") == "1"
    if force or not LAST_SCAN_CACHE:
        LAST_SCAN_CACHE = discover_all_cameras()
    return jsonify({"devices": LAST_SCAN_CACHE})


@app.route("/api/find_by_code", methods=["POST"])
def api_find_by_code():
    data = request.get_json(force=True)
    code = data.get("code", "").strip()
    custom_name = data.get("name", "").strip()
    scope = data.get("scope", "4k")

    global LAST_SCAN_CACHE
    if not LAST_SCAN_CACHE:
        LAST_SCAN_CACHE = discover_all_cameras()

    if scope == "4k":
        target_ips = ["192.168.1.152", "192.168.1.156", "192.168.1.184"]
    else:
        target_ips = [d["ip"] for d in LAST_SCAN_CACHE if d.get("rtsp_open")]

    found_ip = None
    stream_info = None

    def try_ip(ip):
        res = verify_camera_stream(ip, "admin", code)
        return (ip, res)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for ip, res in ex.map(try_ip, target_ips):
            if res.get("ok"):
                found_ip = ip
                stream_info = res
                break

    if not found_ip or not stream_info:
        return jsonify({
            "ok": False,
            "error": (
                f"Ninguna cámara aceptó '{code}' en este momento. Si la cámara recibió varios intentos fallidos, "
                f"reiníciala desde la App EZVIZ (o espera unos minutos) o verifica si se cambió la clave en la App."
            ),
        })

    cams = load_cameras()
    dev_meta = next((d for d in LAST_SCAN_CACHE if d["ip"] == found_ip), {})
    cam_id = f"cam_{found_ip.split('.')[-1]}"
    new_cam = {
        "id": cam_id,
        "name": custom_name or f"Cámara EZVIZ {dev_meta.get('model', '')} ({found_ip})",
        "ip": found_ip,
        "mac": dev_meta.get("mac", ""),
        "brand": dev_meta.get("brand", "EZVIZ"),
        "model": dev_meta.get("model", "CS-H6c-R200-8H8WFL"),
        "serial": dev_meta.get("serial", ""),
        "port": 554,
        "user": "admin",
        "password": code,
        "rtsp_main": stream_info["rtsp_main"],
        "rtsp_sub": stream_info["rtsp_sub"],
        "width": stream_info["width"],
        "height": stream_info["height"],
        "codec": stream_info["codec"],
    }
    cams = [c for c in cams if c["id"] != cam_id]
    cams.append(new_cam)
    save_cameras(cams)
    return jsonify({"ok": True, "camera": new_cam})


@app.route("/api/cameras/add", methods=["POST"])
def api_add_camera():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    user = data.get("user", "admin").strip()
    password = data.get("password", "").strip()
    port = int(data.get("port", 554))
    path = data.get("path", "").strip()
    brand = data.get("brand", "EZVIZ")
    name = data.get("name", "").strip() or f"Cámara {brand} ({ip})"

    check = verify_camera_stream(ip, user, password, port=port, custom_path=path)
    if not check.get("ok"):
        return jsonify({"ok": False, "error": check.get("error", "No se pudo conectar")})

    cams = load_cameras()
    dev_meta = next((d for d in LAST_SCAN_CACHE if d["ip"] == ip), {})
    cam_id = f"cam_{ip.split('.')[-1]}"
    new_cam = {
        "id": cam_id,
        "name": name,
        "ip": ip,
        "mac": dev_meta.get("mac", ""),
        "brand": brand,
        "model": dev_meta.get("model", brand),
        "serial": dev_meta.get("serial", ""),
        "port": port,
        "user": user,
        "password": password,
        "rtsp_main": check["rtsp_main"],
        "rtsp_sub": check["rtsp_sub"],
        "width": check["width"],
        "height": check["height"],
        "codec": check["codec"],
    }
    cams = [c for c in cams if c["id"] != cam_id]
    cams.append(new_cam)
    save_cameras(cams)
    return jsonify({"ok": True, "camera": new_cam})


@app.route("/api/record/<cam_id>/<action>", methods=["POST"])
def api_record(cam_id: str, action: str):
    if action == "start":
        ok, msg = recorder.start_recording(cam_id, persist_24_7=True)
    else:
        ok, msg = recorder.stop_recording(cam_id, persist_24_7=True)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/record_all/<action>", methods=["POST"])
def api_record_all(action: str):
    cams = load_cameras()
    for c in cams:
        if action == "start":
            recorder.start_recording(c["id"], persist_24_7=True)
        else:
            recorder.stop_recording(c["id"], persist_24_7=True)
    msg = "✅ Grabación continua 24/7 activada en todas las cámaras" if action == "start" else "⏹ Grabación detenida en todas las cámaras"
    return jsonify({"ok": True, "message": msg})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json(force=True)
        try:
            updated = save_settings(data)
            recorder.enforce_storage_quota()
            return jsonify({"ok": True, "settings": updated})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify(load_settings())


@app.route("/api/storage_status")
def api_storage_status():
    return jsonify(recorder.get_storage_stats())


@app.route("/api/recordings")
def api_recordings():
    return jsonify({"recordings": recorder.list_recordings()})


@app.route("/api/recordings/download/<path:rel_path>")
def api_download_recording(rel_path: str):
    settings = load_settings()
    return send_from_directory(settings["storage_dir"], rel_path, as_attachment=True)


@app.route("/api/recordings/stream/<path:rel_path>")
def api_stream_recording(rel_path: str):
    """Transcodifica grabaciones HEVC 4K al vuelo a MP4 H.264 fragmentado para reproducción inmediata en el navegador."""
    settings = load_settings()
    full_path = os.path.abspath(os.path.join(settings["storage_dir"], rel_path))
    if not os.path.exists(full_path):
        return "No encontrado", 404

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-i", full_path,
        "-vf", "scale=1920:-2",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "25",
        "-c:a", "aac",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def generate():
        try:
            while True:
                data = proc.stdout.read(16384)
                if not data:
                    break
                yield data
        finally:
            proc.terminate()

    return Response(generate(), mimetype="video/mp4")


@app.route("/api/recordings/open_native", methods=["POST"])
def api_open_recording_native():
    data = request.get_json(force=True)
    rel_path = data.get("rel_path", "")
    settings = load_settings()
    full_path = os.path.abspath(os.path.join(settings["storage_dir"], rel_path))
    if not os.path.exists(full_path):
        return jsonify({"ok": False, "error": "No encontrado"}), 404
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0.0")
    subprocess.Popen(["ffplay", "-nostats", "-window_title", f"Grabación 4K: {rel_path}", full_path], env=env)
    return jsonify({"ok": True})


@app.route("/api/recordings/recover_file", methods=["POST"])
def api_recover_file():
    data = request.get_json(force=True)
    res = recorder.recover_video_file(data.get("rel_path", ""))
    return jsonify(res)


@app.route("/api/recordings/recover_range", methods=["POST"])
def api_recover_range():
    data = request.get_json(force=True)
    res = recorder.recover_time_range(
        cam_id=data.get("cam_id", ""),
        date_str=data.get("date_str", ""),
        start_time=data.get("start_time", "00:00"),
        end_time=data.get("end_time", "23:59"),
    )
    return jsonify(res)


@app.route("/capturas/<path:filename>")
def serve_captures(filename: str):
    return send_from_directory(CAPTURES_DIR, filename)


@app.route("/recuperados/<path:filename>")
def serve_recovered(filename: str):
    rec_dir = os.path.join(os.path.abspath(load_settings()["storage_dir"]), "_recuperados")
    return send_from_directory(rec_dir, filename, as_attachment=True)


@app.route("/api/cameras/update_password", methods=["POST"])
def api_update_camera_password():
    data = request.get_json(force=True)
    cam_id = data.get("id", "")
    new_pass = data.get("password", "").strip()
    cams = load_cameras()
    target = None
    for c in cams:
        if c["id"] == cam_id:
            c["password"] = new_pass
            c["rtsp_main"] = f"rtsp://{c.get('user', 'admin')}:{new_pass}@{c['ip']}:{c.get('port', 554)}/ch1/main"
            c["rtsp_sub"] = f"rtsp://{c.get('user', 'admin')}:{new_pass}@{c['ip']}:{c.get('port', 554)}/ch1/sub"
            target = c
            break
    if not target:
        return jsonify({"ok": False, "error": "Cámara no encontrada"}), 404
    save_cameras(cams)
    return jsonify({"ok": True, "camera": target})


if __name__ == "__main__":
    bind_host = os.environ.get("NVR_BIND_HOST", "127.0.0.1")
    bind_port = int(os.environ.get("NVR_PORT", "5050"))
    print("==========================================================")
    print("🛡️ Sistema NVR Local EZVIZ / ONVIF / RTSP iniciado")
    print(f"🔒 Panel Web (SOLO INTERNO): http://{bind_host}:{bind_port}")
    print("==========================================================")
    app.run(host=bind_host, port=bind_port, threaded=True)
