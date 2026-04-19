#!/usr/bin/env python3
"""
ArgOS Spot Downloader
Descarga música de Spotify con metadatos completos usando spotdl.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

import threading
import subprocess
import os
import re
import shutil
from pathlib import Path

APP_ID  = "com.argos.spotdownloader"
VERSION = "1.0.0"

# ── Helpers ──────────────────────────────────────────────────────────────────

ANSI_RE = re.compile(r'\x1B\[[0-9;]*[mK]')

def strip_ansi(text: str) -> str:
    return ANSI_RE.sub('', text)


# ── Track row widget ──────────────────────────────────────────────────────────

class TrackRow(Gtk.ListBoxRow):
    def __init__(self, title: str):
        super().__init__()
        self.set_selectable(False)
        self.title = title

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(14)
        box.set_margin_end(14)

        self._icon = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        self._icon.set_pixel_size(16)
        box.append(self._icon)

        label = Gtk.Label(label=title)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(50)
        box.append(label)

        self._status = Gtk.Label(label="En cola")
        self._status.add_css_class("dim-label")
        self._status.set_width_chars(12)
        self._status.set_xalign(1.0)
        box.append(self._status)

        self.set_child(box)

    def set_downloading(self):
        self._icon.set_from_icon_name("emblem-synchronizing-symbolic")
        self._status.set_text("Descargando…")
        self._status.remove_css_class("success")
        self._status.remove_css_class("warning")
        self._status.remove_css_class("error")

    def set_done(self):
        self._icon.set_from_icon_name("emblem-ok-symbolic")
        self._status.set_text("✓ Listo")
        self._status.add_css_class("success")

    def set_skipped(self):
        self._icon.set_from_icon_name("edit-redo-symbolic")
        self._status.set_text("Omitido")
        self._status.add_css_class("warning")

    def set_error(self):
        self._icon.set_from_icon_name("dialog-error-symbolic")
        self._status.set_text("Error")
        self._status.add_css_class("error")


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(Adw.ApplicationWindow):

    FORMAT_MAP = ["opus", "mp3", "m4a", "flac", "ogg", "wav"]
    FORMAT_LABELS = [
        "Opus  (recomendado ★)",
        "MP3",
        "M4A / AAC",
        "FLAC (sin pérdida)",
        "OGG Vorbis",
        "WAV  (sin comprimir)",
    ]

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("ArgOS Spot Downloader")
        self.set_default_size(620, 600)
        self.set_size_request(460, 480)

        self._output_dir    = str(Path.home() / "Música")
        self._process       = None
        self._is_running    = False
        self._track_rows: dict[str, TrackRow] = {}
        self._total         = 0
        self._downloaded    = 0

        self._build_ui()
        self._check_spotdl()

    # ── UI builder ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Toast overlay wraps everything
        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)

        toolbar_view = Adw.ToolbarView()
        self._toast.set_child(toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        about_btn = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about_btn.set_tooltip_text("Acerca de")
        about_btn.connect("clicked", self._on_about)
        header.pack_end(about_btn)
        toolbar_view.add_top_bar(header)

        # Scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(620)
        clamp.set_tightening_threshold(580)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(24)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)

        # ── Banner (spotdl ausente) ──
        self._banner = Adw.Banner()
        self._banner.set_title("spotdl no encontrado — instálalo: pip install spotdl")
        self._banner.set_button_label("Ocultar")
        self._banner.connect("button-clicked", lambda b: b.set_revealed(False))
        vbox.append(self._banner)

        # ── Grupo URL ──
        url_group = Adw.PreferencesGroup()
        url_group.set_title("Enlace de Spotify")
        url_group.set_description("Canción, álbum o playlist")

        url_row = Adw.ActionRow()
        url_row.set_title("URL")

        self._url_entry = Gtk.Entry()
        self._url_entry.set_placeholder_text("https://open.spotify.com/…")
        self._url_entry.set_hexpand(True)
        self._url_entry.set_valign(Gtk.Align.CENTER)
        self._url_entry.connect("changed", self._on_url_changed)
        self._url_entry.connect("activate", lambda *_: self._try_download())

        paste_btn = Gtk.Button.new_from_icon_name("edit-paste-symbolic")
        paste_btn.set_tooltip_text("Pegar del portapapeles")
        paste_btn.set_valign(Gtk.Align.CENTER)
        paste_btn.add_css_class("flat")
        paste_btn.connect("clicked", self._on_paste)

        clear_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        clear_btn.set_tooltip_text("Limpiar")
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", lambda *_: self._url_entry.set_text(""))

        url_row.add_suffix(self._url_entry)
        url_row.add_suffix(paste_btn)
        url_row.add_suffix(clear_btn)
        url_group.add(url_row)
        vbox.append(url_group)

        # ── Grupo configuración ──
        cfg_group = Adw.PreferencesGroup()
        cfg_group.set_title("Configuración")

        # Formato
        fmt_list = Gtk.StringList()
        for lbl in self.FORMAT_LABELS:
            fmt_list.append(lbl)
        self._fmt_row = Adw.ComboRow()
        self._fmt_row.set_title("Formato")
        self._fmt_row.set_subtitle("Opus: mejor calidad/tamaño con metadatos completos")
        self._fmt_row.set_model(fmt_list)
        self._fmt_row.set_selected(0)
        cfg_group.add(self._fmt_row)

        # Carpeta destino
        self._folder_row = Adw.ActionRow()
        self._folder_row.set_title("Carpeta de destino")
        self._folder_row.set_subtitle(self._output_dir)
        self._folder_row.set_activatable(True)
        self._folder_row.connect("activated", self._on_choose_folder)

        folder_icon = Gtk.Image.new_from_icon_name("folder-open-symbolic")
        folder_icon.set_valign(Gtk.Align.CENTER)
        self._folder_row.add_suffix(folder_icon)
        cfg_group.add(self._folder_row)

        vbox.append(cfg_group)

        # ── Botones ──
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)

        self._download_btn = Gtk.Button(label="  Descargar  ")
        self._download_btn.add_css_class("suggested-action")
        self._download_btn.add_css_class("pill")
        self._download_btn.set_sensitive(False)
        self._download_btn.connect("clicked", lambda *_: self._try_download())
        btn_box.append(self._download_btn)

        self._cancel_btn = Gtk.Button(label="Cancelar")
        self._cancel_btn.add_css_class("destructive-action")
        self._cancel_btn.add_css_class("pill")
        self._cancel_btn.set_visible(False)
        self._cancel_btn.connect("clicked", self._on_cancel)
        btn_box.append(self._cancel_btn)

        vbox.append(btn_box)

        # ── Progreso ──
        self._progress_group = Adw.PreferencesGroup()
        self._progress_group.set_title("Progreso")
        self._progress_group.set_visible(False)

        prog_row = Adw.ActionRow()
        self._prog_title = prog_row

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_hexpand(True)
        self._progress_bar.set_valign(Gtk.Align.CENTER)
        self._progress_bar.set_show_text(True)
        self._progress_bar.set_text("Iniciando…")
        prog_row.add_suffix(self._progress_bar)
        self._progress_group.add(prog_row)
        vbox.append(self._progress_group)

        # ── Lista de pistas ──
        self._tracks_group = Adw.PreferencesGroup()
        self._tracks_group.set_title("Pistas")
        self._tracks_group.set_visible(False)

        self._tracks_list = Gtk.ListBox()
        self._tracks_list.add_css_class("boxed-list")
        self._tracks_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._tracks_group.add(self._tracks_list)
        vbox.append(self._tracks_group)

        clamp.set_child(vbox)
        scroll.set_child(clamp)
        toolbar_view.set_content(scroll)

    # ── Checks & helpers ──────────────────────────────────────────────────────

    def _check_spotdl(self):
        if shutil.which("spotdl") is None:
            self._banner.set_revealed(True)

    def _fmt(self) -> str:
        return self.FORMAT_MAP[self._fmt_row.get_selected()]

    def _toast_notify(self, msg: str, timeout: int = 3):
        t = Adw.Toast.new(msg)
        t.set_timeout(timeout)
        self._toast.add_toast(t)

    def _set_running(self, running: bool):
        self._is_running = running
        self._download_btn.set_visible(not running)
        self._cancel_btn.set_visible(running)
        url = self._url_entry.get_text().strip()
        self._download_btn.set_sensitive("spotify.com" in url)

    def _clear_track_list(self):
        self._track_rows.clear()
        child = self._tracks_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._tracks_list.remove(child)
            child = nxt

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _on_url_changed(self, entry):
        url = entry.get_text().strip()
        self._download_btn.set_sensitive("spotify.com" in url and not self._is_running)

    def _on_paste(self, *_):
        self.get_clipboard().read_text_async(None, self._finish_paste)

    def _finish_paste(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
            if text:
                GLib.idle_add(self._url_entry.set_text, text.strip())
        except Exception:
            pass

    def _on_choose_folder(self, *_):
        dlg = Gtk.FileDialog()
        dlg.set_title("Seleccionar carpeta de destino")
        initial = Gio.File.new_for_path(self._output_dir) \
            if os.path.isdir(self._output_dir) else None
        if initial:
            dlg.set_initial_folder(initial)
        dlg.select_folder(self, None, self._finish_folder)

    def _finish_folder(self, dlg, result):
        try:
            folder = dlg.select_folder_finish(result)
            if folder:
                self._output_dir = folder.get_path()
                self._folder_row.set_subtitle(self._output_dir)
        except Exception:
            pass

    def _on_cancel(self, *_):
        if self._process and self._process.poll() is None:
            self._process.terminate()
        self._set_running(False)
        self._progress_bar.set_text("Cancelado")
        self._toast_notify("⏹ Descarga cancelada")

    def _on_about(self, *_):
        dlg = Adw.AboutDialog()
        dlg.set_application_name("ArgOS Spot Downloader")
        dlg.set_version(VERSION)
        dlg.set_developer_name("Tavo78ok")
        dlg.set_application_icon("audio-x-generic-symbolic")
        dlg.set_comments(
            "Descarga canciones, álbumes y playlists de Spotify "
            "con metadatos e imagen de portada completos.\n\n"
            "Requiere spotdl instalado en el sistema."
        )
        dlg.set_license_type(Gtk.License.GPL_3_0)
        dlg.set_website("https://github.com/Tavo78ok")
        dlg.present(self)

    # ── Download logic ────────────────────────────────────────────────────────

    def _try_download(self):
        if self._is_running:
            return
        # Read widget values on main thread BEFORE spawning worker
        url     = self._url_entry.get_text().strip()
        fmt     = self._fmt()
        out_dir = self._output_dir

        if "spotify.com" not in url:
            self._toast_notify("⚠ Pega un enlace válido de Spotify")
            return

        self._clear_track_list()
        self._total      = 0
        self._downloaded = 0
        self._track_rows = {}

        self._progress_group.set_visible(True)
        self._tracks_group.set_visible(True)
        self._progress_bar.set_fraction(0)
        self._progress_bar.set_text("Conectando…")
        self._prog_title.set_title("Iniciando descarga…")

        self._set_running(True)

        threading.Thread(
            target=self._worker,
            args=(url, fmt, out_dir),
            daemon=True
        ).start()

    def _worker(self, url: str, fmt: str, out_dir: str):
        try:
            os.makedirs(out_dir, exist_ok=True)
            cmd = [
                "spotdl", "download", url,
                "--format", fmt,
                "--output", out_dir,
                "--print-errors",
            ]
            env = os.environ.copy()
            env["NO_COLOR"] = "1"   # disable Rich colours

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            for raw_line in self._process.stdout:
                line = strip_ansi(raw_line).strip()
                if line:
                    GLib.idle_add(self._parse_line, line)

            self._process.wait()
            rc = self._process.returncode
            GLib.idle_add(self._on_done, rc == 0)

        except FileNotFoundError:
            GLib.idle_add(self._on_no_spotdl)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    # ── Output parsing (main thread via idle_add) ─────────────────────────────

    def _parse_line(self, line: str):
        ll = line.lower()

        # Total found  →  "Found X songs in …"
        m = re.search(r'found\s+(\d+)\s+song', ll)
        if m:
            self._total = int(m.group(1))
            self._prog_title.set_title(f"Descargando {self._total} pista(s)…")
            return

        # Downloading  →  "Downloading Song Name…"
        if ll.startswith("downloading"):
            song = line[len("downloading"):].strip().rstrip(".")
            if song and song not in self._track_rows:
                row = TrackRow(song)
                row.set_downloading()
                self._tracks_list.append(row)
                self._track_rows[song] = row
            return

        # Downloaded  →  "Downloaded "Song" to /path"
        m = re.match(r'downloaded\s+"?(.+?)"?\s+to\s+', line, re.IGNORECASE)
        if m:
            song = m.group(1).strip()
            self._downloaded += 1
            self._update_progress()
            row = self._find_row(song)
            if row:
                row.set_done()
            else:
                row = TrackRow(song)
                row.set_done()
                self._tracks_list.append(row)
                self._track_rows[song] = row
            return

        # Skipping  →  "Skipping … already exists"
        if "skipping" in ll or "already downloaded" in ll:
            self._downloaded += 1
            self._update_progress()
            # Try to extract name
            m = re.search(r'skipping\s+"?(.+?)"?(?:\s*\(|$)', line, re.IGNORECASE)
            if m:
                song = m.group(1).strip()
                row = self._find_row(song)
                if row:
                    row.set_skipped()
                else:
                    row = TrackRow(song)
                    row.set_skipped()
                    self._tracks_list.append(row)
                    self._track_rows[song] = row
            return

        # Error lines
        if "error" in ll or "couldn't" in ll or "failed" in ll:
            # Mark last "downloading" row as error if we can
            m = re.search(r'"([^"]+)"', line)
            if m:
                row = self._find_row(m.group(1))
                if row:
                    row.set_error()

    def _find_row(self, name: str) -> TrackRow | None:
        """Fuzzy-find a row by checking if name is a substring of row titles."""
        if name in self._track_rows:
            return self._track_rows[name]
        for key, row in self._track_rows.items():
            if name.lower() in key.lower() or key.lower() in name.lower():
                return row
        return None

    def _update_progress(self):
        total = self._total or max(self._downloaded, 1)
        frac  = min(self._downloaded / total, 1.0)
        self._progress_bar.set_fraction(frac)
        self._progress_bar.set_text(f"{self._downloaded} / {total}")

    # ── Completion callbacks (main thread) ────────────────────────────────────

    def _on_done(self, success: bool):
        self._set_running(False)
        self._progress_bar.set_fraction(1.0)
        if success:
            self._progress_bar.set_text("¡Completado!")
            self._prog_title.set_title("Descarga finalizada")
            self._toast_notify("✅ ¡Descarga completada!")
        else:
            self._progress_bar.set_text("Finalizado con errores")
            self._toast_notify("⚠ Descarga finalizada con algunos errores", timeout=5)

    def _on_no_spotdl(self):
        self._set_running(False)
        self._banner.set_revealed(True)
        self._progress_group.set_visible(False)
        self._tracks_group.set_visible(False)
        self._toast_notify("❌ spotdl no está instalado", timeout=5)

    def _on_error(self, msg: str):
        self._set_running(False)
        self._progress_bar.set_text("Error")
        self._toast_notify(f"❌ Error: {msg}", timeout=5)


# ── Application ───────────────────────────────────────────────────────────────

class SpotDownloaderApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", lambda app: MainWindow(app).present())


def main():
    import sys
    app = SpotDownloaderApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
