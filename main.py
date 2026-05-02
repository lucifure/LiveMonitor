"""
YouTube Live Monitor — Kivy Android App (FIXED)

Fixes:
  1. Uses yt-dlp as a Python library (not a shell command) → no Permission denied
  2. SSL fix via certifi → ffmpeg download works
  3. ffmpeg downloaded using requests+certifi instead of urllib
  4. Better UI sizing for Android screens
  5. Proper save path for Android 10+ (app-private dir fallback)
"""

import os
import re
import ssl
import time
import threading
import subprocess
from datetime import datetime

# ── Kivy config MUST happen before any kivy imports ──────────────────────────
from kivy.config import Config
Config.set('graphics', 'resizable', '0')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.utils import platform
from kivy.metrics import dp, sp
from kivy.core.window import Window

# ── Android-only imports ──────────────────────────────────────────────────────
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass

# ── Constants ─────────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Use app-private directory (always writable, no MANAGE_EXTERNAL_STORAGE needed)
if platform == 'android':
    from jnius import autoclass as _ac
    try:
        PythonActivity = _ac('org.kivy.android.PythonActivity')
        _ext = PythonActivity.mActivity.getExternalFilesDir(None)
        DOWNLOAD_DIR = str(_ext.getAbsolutePath()) + '/Recordings'
    except Exception:
        DOWNLOAD_DIR = os.path.join(APP_DIR, 'Recordings')
else:
    DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'YouTubeMonitor')

FFMPEG_BIN  = os.path.join(APP_DIR, 'ffmpeg')
POLL_INTERVAL = 60  # seconds

FFMPEG_URL = (
    'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/'
    'ffmpeg-master-latest-android-arm64-gpl.tar.xz'
)

_CHANNEL_RE = re.compile(
    r'youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)(/live)?$'
)

def resolve_live_url(url: str) -> str:
    url = url.rstrip('/')
    if _CHANNEL_RE.search(url):
        if not url.endswith('/live'):
            return url + '/live'
    return url

def make_ssl_context():
    """Return a verified SSL context using certifi certs."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except Exception:
        return ssl.create_default_context()

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG       = (0.07, 0.07, 0.10, 1)
C_PANEL    = (0.11, 0.11, 0.16, 1)
C_BLUE     = (0.25, 0.45, 0.95, 1)
C_RED      = (0.80, 0.25, 0.25, 1)
C_TEXT     = (0.88, 0.90, 0.95, 1)
C_MUTED    = (0.45, 0.50, 0.65, 1)
C_GREEN    = (0.20, 0.80, 0.50, 1)
C_ORANGE   = (0.95, 0.65, 0.15, 1)

# ── Main App ──────────────────────────────────────────────────────────────────
class LiveMonitorApp(App):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._running   = False
        self._wake_lock = None
        self._log_lines = []
        self._ytdlp_thread = None

    # ── Build UI ──────────────────────────────────────────────────────────────
    def build(self):
        self.title = 'YouTube Live Monitor'
        Window.clearcolor = C_BG

        root = BoxLayout(
            orientation='vertical',
            padding=dp(12),
            spacing=dp(8),
        )

        # ── URL input ──
        self.url_input = TextInput(
            hint_text='Paste YouTube channel or video URL…',
            hint_text_color=(*C_MUTED[:3], 1),
            foreground_color=C_TEXT,
            background_color=C_PANEL,
            cursor_color=C_TEXT,
            multiline=False,
            size_hint_y=None,
            height=dp(50),
            font_size=sp(14),
            padding=[dp(12), dp(12)],
        )
        root.add_widget(self.url_input)

        # ── Buttons ──
        btn_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))

        self.start_btn = Button(
            text='▶  Start Monitor',
            background_color=C_BLUE,
            color=C_TEXT,
            font_size=sp(14),
            bold=True,
        )
        self.start_btn.bind(on_press=self._on_start)

        self.stop_btn = Button(
            text='⏹  Stop',
            background_color=C_RED,
            color=C_TEXT,
            font_size=sp(14),
            bold=True,
            disabled=True,
        )
        self.stop_btn.bind(on_press=self._on_stop)

        btn_row.add_widget(self.start_btn)
        btn_row.add_widget(self.stop_btn)
        root.add_widget(btn_row)

        # ── Status bar ──
        self.status_lbl = Label(
            text='Ready.',
            size_hint_y=None,
            height=dp(26),
            font_size=sp(12),
            color=(*C_MUTED[:3], 1),
            halign='left',
            valign='middle',
        )
        self.status_lbl.bind(size=self.status_lbl.setter('text_size'))
        root.add_widget(self.status_lbl)

        # ── Save path label ──
        path_lbl = Label(
            text=f'Save → {DOWNLOAD_DIR}',
            size_hint_y=None,
            height=dp(20),
            font_size=sp(10),
            color=(*C_MUTED[:3], 0.7),
            halign='left',
            valign='middle',
        )
        path_lbl.bind(size=path_lbl.setter('text_size'))
        root.add_widget(path_lbl)

        # ── Log scroll ──
        self._scroll = ScrollView(size_hint=(1, 1))
        self.log_lbl = Label(
            text='',
            font_size=sp(11),
            halign='left',
            valign='top',
            size_hint_y=None,
            markup=True,
            padding=[dp(6), dp(6)],
            color=C_TEXT,
        )
        self.log_lbl.bind(texture_size=self._sync_log_height)
        self._scroll.add_widget(self.log_lbl)
        root.add_widget(self._scroll)

        # ── Bootstrap ──
        self._request_android_permissions()
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        Clock.schedule_once(lambda _: self._ensure_ffmpeg_async(), 1.5)

        return root

    def _sync_log_height(self, instance, value):
        instance.height = max(value[1], self._scroll.height)

    # ── Logging ───────────────────────────────────────────────────────────────
    def log(self, msg: str, color: str = 'dde2f0'):
        ts   = datetime.now().strftime('%H:%M:%S')
        line = f'[color=556080][{ts}][/color] [color={color}]{msg}[/color]'
        self._log_lines.append(line)
        if len(self._log_lines) > 400:
            self._log_lines = self._log_lines[-400:]
        Clock.schedule_once(self._flush_log, 0)

    def _flush_log(self, *_):
        self.log_lbl.text = '\n'.join(self._log_lines)
        Clock.schedule_once(lambda *_: setattr(self._scroll, 'scroll_y', 0), 0.05)

    def set_status(self, msg: str, color=C_MUTED):
        def _do(*_):
            self.status_lbl.text  = msg
            self.status_lbl.color = (*color[:3], 1)
        Clock.schedule_once(_do, 0)

    # ── Permissions ───────────────────────────────────────────────────────────
    def _request_android_permissions(self):
        if platform != 'android':
            return
        perms = [Permission.INTERNET, Permission.WAKE_LOCK]
        # Storage perms (older Android; not needed for app-private dir but harmless)
        try:
            perms += [Permission.READ_EXTERNAL_STORAGE,
                      Permission.WRITE_EXTERNAL_STORAGE]
        except AttributeError:
            pass
        request_permissions(perms)

    # ── Wake lock ─────────────────────────────────────────────────────────────
    def _acquire_wake_lock(self):
        if platform != 'android':
            return
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context        = autoclass('android.content.Context')
            PowerManager   = autoclass('android.os.PowerManager')
            pm = PythonActivity.mActivity.getSystemService(Context.POWER_SERVICE)
            self._wake_lock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                'LiveMonitor::WakeLock',
            )
            self._wake_lock.acquire()
            self.log('Wake lock acquired — CPU stays on.', color='33cc88')
        except Exception as exc:
            self.log(f'Wake lock warning: {exc}', color='f5a623')

    def _release_wake_lock(self):
        if self._wake_lock is None:
            return
        try:
            if self._wake_lock.isHeld():
                self._wake_lock.release()
            self.log('Wake lock released.')
        except Exception:
            pass
        self._wake_lock = None

    # ── ffmpeg bootstrap ──────────────────────────────────────────────────────
    def _ensure_ffmpeg_async(self):
        threading.Thread(target=self._ensure_ffmpeg, daemon=True).start()

    def _ensure_ffmpeg(self):
        if os.path.exists(FFMPEG_BIN):
            self.log(f'ffmpeg already present.')
            return
        self.log('Downloading ffmpeg binary (~10 MB)…', color='f5a623')
        try:
            import tarfile, requests, certifi
            tmp = FFMPEG_BIN + '.tar.xz'
            r = requests.get(FFMPEG_URL, stream=True, verify=certifi.where(), timeout=60)
            r.raise_for_status()
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
            with tarfile.open(tmp, 'r:xz') as tf:
                for member in tf.getmembers():
                    if member.name.endswith('/ffmpeg') and not member.isdir():
                        member.name = 'ffmpeg'
                        tf.extract(member, APP_DIR)
                        break
            os.remove(tmp)
            os.chmod(FFMPEG_BIN, 0o755)
            self.log('ffmpeg ready!', color='33cc88')
        except Exception as exc:
            self.log(f'ffmpeg download failed: {exc}', color='e05252')
            self.log('Recording will still work — yt-dlp handles most streams.', color='f5a623')

    # ── Button handlers ───────────────────────────────────────────────────────
    def _on_start(self, *_):
        url = self.url_input.text.strip()
        if not url:
            self.set_status('⚠ Please enter a YouTube URL.', C_RED)
            return
        self._running = True
        self.start_btn.disabled  = True
        self.stop_btn.disabled   = False
        self.url_input.disabled  = True
        self.set_status('Monitor running…', C_BLUE)
        self._acquire_wake_lock()
        threading.Thread(
            target=self._monitor_loop, args=(url,), daemon=True
        ).start()

    def _on_stop(self, *_):
        self._running = False
        self._release_wake_lock()
        self.start_btn.disabled  = False
        self.stop_btn.disabled   = True
        self.url_input.disabled  = False
        self.set_status('Stopped.', C_MUTED)
        self.log('▪ Monitor stopped by user.')

    # ── Monitor loop ──────────────────────────────────────────────────────────
    def _monitor_loop(self, url: str):
        live_url = resolve_live_url(url)
        self.log(f'Monitoring  → {url}')
        self.log(f'Check URL   → {live_url}')
        self.log(f'Saving to   → {DOWNLOAD_DIR}')

        while self._running:
            self.set_status('Checking if live…', C_BLUE)
            self.log('Checking live status…')

            is_live = self._check_live(live_url)
            if not self._running:
                break

            if not is_live:
                self.log(f'Not live. Next check in {POLL_INTERVAL}s…', color='f5a623')
                self.set_status(f'Not live — next check in {POLL_INTERVAL}s', C_ORANGE)
                self._sleep(POLL_INTERVAL)
                continue

            self.log('● LIVE detected — recording!', color='e05252')
            self.set_status('● Recording…', C_RED)
            self._record(live_url)

            if not self._running:
                break
            self.log(f'Recording done. Next check in {POLL_INTERVAL}s…', color='33cc88')
            self.set_status(f'Stream ended — next check in {POLL_INTERVAL}s', C_GREEN)
            self._sleep(POLL_INTERVAL)

        self.log('Monitor loop exited.')

    def _sleep(self, seconds: int):
        for _ in range(seconds):
            if not self._running:
                return
            time.sleep(1)

    # ── Live check via yt-dlp Python API ─────────────────────────────────────
    def _check_live(self, url: str) -> bool:
        """Use yt-dlp as a Python library — no subprocess, no Permission denied."""
        try:
            import yt_dlp
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'socket_timeout': 20,
                'simulate': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                # is_live is True when actively streaming
                return bool(info and info.get('is_live'))
        except Exception as exc:
            err = str(exc)
            if 'This live event will begin' in err or 'Premieres in' in err:
                self.log('Stream scheduled but not started yet.', color='f5a623')
            elif 'not a live' in err.lower() or 'no video formats' in err.lower():
                pass  # expected when offline
            else:
                self.log(f'Check error: {exc}', color='f5a623')
            return False

    # ── Record via yt-dlp Python API ─────────────────────────────────────────
    def _record(self, url: str):
        try:
            import yt_dlp
            ts      = datetime.now().strftime('%d%m%Y_%H%M')
            out_tpl = os.path.join(DOWNLOAD_DIR, f'%(title)s_{ts}.%(ext)s')

            ydl_opts = {
                'outtmpl':              out_tpl,
                'quiet':                False,
                'no_warnings':          True,
                'noplaylist':           True,
                'merge_output_format':  'mp4',
                'restrictfilenames':    True,
                'nopart':               True,
                'progress_hooks':       [self._ydlp_progress],
                'logger':               _YdlLogger(self.log),
            }
            if os.path.exists(FFMPEG_BIN):
                ydl_opts['ffmpeg_location'] = FFMPEG_BIN

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        except Exception as exc:
            self.log(f'Recording error: {exc}', color='e05252')

    def _ydlp_progress(self, d):
        status = d.get('status', '')
        if status == 'downloading':
            pct   = d.get('_percent_str', '').strip()
            speed = d.get('_speed_str', '').strip()
            if pct:
                self.set_status(f'Recording {pct} @ {speed}', C_RED)
        elif status == 'finished':
            fname = os.path.basename(d.get('filename', ''))
            self.log(f'✓ Saved: {fname}', color='33cc88')


class _YdlLogger:
    """Pipe yt-dlp log messages to the app log."""
    def __init__(self, log_fn):
        self._log = log_fn
    def debug(self, msg):
        if msg.startswith('[debug]'):
            return
        self._log(msg)
    def info(self, msg):
        self._log(msg)
    def warning(self, msg):
        self._log(f'[warn] {msg}', color='f5a623')
    def error(self, msg):
        self._log(f'[err] {msg}', color='e05252')


if __name__ == '__main__':
    LiveMonitorApp().run()
