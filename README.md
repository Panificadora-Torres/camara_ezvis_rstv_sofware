# 🛡️ Sistema NVR Local 24/7 (EZVIZ 4K / ONVIF / RTSP)

Sistema de videovigilancia local nativo para Linux (sin Docker, con acceso directo a la red local para detección SADP/ONVIF/RTSP) y panel de administración 100% Web (`http://IP_SERVIDOR:5050`).

## 🚀 Uso Rápido en Cualquier Servidor Linux

Para iniciar todo el sistema en segundo plano (desacoplado de la terminal para que siga corriendo 24/7 aunque cierres SSH):

```bash
bash start.sh
```

Para detener el servicio:

```bash
bash stop.sh
```

Para ver los logs en tiempo real:

```bash
tail -f nvr.log
```

---

## ✨ Características Principales
1. **Visor 4K Nativo (`3840×2160`) + Zoom Digital Interactivo (`1x` a `10x`):**
   - Usa la rueda del mouse sobre el video para hacer zoom y arrastra con clic izquierdo para moverte por la imagen 4K.
2. **Escáner Directo de Red Local (SADP + ONVIF + RTSP):**
   - Al correr de forma nativa sobre la red del servidor, descubre directamente todas las cámaras EZVIZ, Hikvision, ONVIF y RTSP mostrando su modelo exacto, número de serie (`SN`), MAC e IP.
3. **Grabación Continua 24/7 con Límite Circular Automático (Mínimo 500 GB / 1 TB+):**
   - Desde la pestaña **`💾 Grabaciones y Recovery`** indicas la ruta de la carpeta local y el límite máximo en GB (**mínimo 500 GB**, por defecto **1000 GB = 1 TB**).
   - El sistema monitorea el espacio cada 30 segundos y **elimina automáticamente las grabaciones más antiguas (FIFO)** al llegar al límite.
4. **Recovery de Video:**
   - Reparación e indexación de segmentos interrumpidos y unión/exportación de clips por rango de fecha y hora.
