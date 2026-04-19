### ArgOS Spot Downloader

Descarga canciones, álbumes y playlists de Spotify con metadatos completos
(portada, artista, álbum, año) usando **spotdl** como backend.

## Requisitos

```bash
# Python y dependencias GTK (normalmente ya instaladas en tu distro)
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

# spotdl + ffmpeg
pip install spotdl
sudo apt install ffmpeg
```

## Ejecutar

```bash
python3 main.py
```

## Características

- ✅ Descarga canciones, álbumes y playlists de Spotify
- ✅ Formatos: **Opus** (recomendado), MP3, M4A, FLAC, OGG, WAV
- ✅ Metadatos completos: portada, artista, álbum, año, número de pista
- ✅ Lista de pistas con estado en tiempo real
- ✅ Barra de progreso por pista y global
- ✅ Botón de cancelación
- ✅ Notificaciones toast
- ✅ GTK4 + libadwaita (tema oscuro/claro automático)

## Packaging `.deb`

```
DEBIAN/
  control
  postinst
usr/
  bin/argos-spot-downloader
  share/applications/com.argos.spotdownloader.desktop
  share/argos-spot-downloader/main.py
```

### `DEBIAN/postinst`

```bash
#!/bin/bash
# Instalar spotdl si no está presente
if ! command -v spotdl &>/dev/null; then
    pip3 install spotdl --quiet || true
fi
```
