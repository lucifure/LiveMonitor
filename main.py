"""
YouTube Live Monitor — Kivy Android App
Monitors a YouTube channel URL and automatically records when it goes live.
"""

import os
import re
import time
import threading
import subprocess
import urllib.request
from datetime import datetime

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.utils import platform

# ── Android-only imports ──────────────────────────────────────────────────────
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass

# ── Constants ─────────────────────────────────────────────────────────────────
DOWNLOAD_DIR   = '/storage/emulated/0/Download/YouTubeMonitor'
POLL_INTERVAL  = 60        # seconds between live-status checks
FFMPEG_URL     = (         # static arm64 ffmpeg binary — self-contained, no root needed
    'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/'
    'ffmpeg-master-latest-android-arm64-gpl.tar.xz'
)
APP_DIR        = os.path.dirname(os.path.abspath(__file__))
FFMPEG_BIN     = os.path.join(APP_DIR, 'ffmpeg')

# Detect channel URLs so we can append /live
_CHANNEL_RE = re.compile(
    r'youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)(/live)?$'
)


def resolve_live_url(url: str) -> str:
    """Append /live to channel URLs so yt-dlp targets the active stream."""
    url = url.rstrip('/')
    if _CHANNEL_RE.search(url):
        if not url.endswith('/live'):
            return url + '/live'
    return url


# ── Main UI ───────────────────────────────────────────────────────────────────
class YouTubeMonitorApp(App):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._running       = False
        self._wake_lock     = None
        self._current_proc  = None
        self._log_lines     = []

    # ── Build UI ──────────────────────────────────────────────────────────────
    def build(self):
        self.title = 'YouTube Live Monitor'

        root = BoxLayout(orientation='vertical', padding=14, spacing=10)

        # URL input
        self.url_input = TextInput(
            hint_text='Paste YouTube channel or video URL…',
            multiline=False,
            size_hint_y=None,
            height=52,
            font_size=15,
            padding=[12, 12],
        )
        root.add_widget(self.url_input)

        # Button row
        btn_row = BoxLayout(size_hint_y=None, height=52, spacing=10)

        self.start_btn = Button(
            text='▶  Start Monitor',
            background_color=(0.31, 0.43, 0.97, 1),
            color=(1, 1, 1, 1),
            font_size=15,
            bold=True,
        )
        self.start_btn.bind(on_press=self._on_start)

        self.stop_btn = Button(
            text='⏹  Stop',
            background_color=(0.87, 0.32, 0.32, 1),
            color=(1, 1, 1, 1),
            font_size=15,
            bold=True,
            disabled=True,
        )
        self.stop_btn.bind(on_press=self._on_stop)

        btn_row.add_widget(self.start_btn)
        btn_row.add_widget(self.stop_btn)
        root.add_widget(btn_row)

        # Status bar
        self.status_lbl = Label(
            text='Ready.',
            size_hint_y=None,
            height=28,
            font_size=13,
            color=(0.48, 0.52, 0.66, 1),
            halign='left',
            valign='middle',
        )
        self.status_lbl.bind(size=self.status_lbl.setter('text_size'))
        root.add_widget(self.status_lbl)

        # Scrollable log
        self._scroll = ScrollView()
        self.log_lbl = Label(
            text='',
            font_size=12,
            halign='left',
            valign='top',
            size_hint_y=None,
            markup=True,
            padding=[4, 4],
        )
        self.log_lbl.bind(texture_size=self._sync_log_height)
        self._scroll.add_widget(self.log_lbl)
        root.add_widget(self._scroll)

        # Bootstrap
        self._request_android_permissions()
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        Clock.schedule_once(lambda _: self._ensure_ffmpeg_async(), 1)

        return root

    def _sync_log_height(self, instance, value):
        instance.height = max(value[1], self._scroll.height)

    # ── Logging ───────────────────────────────────────────────────────────────
    def log(self, msg: str, color: str = 'e8ecf5'):
        ts   = datetime.now().strftime('%H:%M:%S')
        line = f'[color=7a84a8][{ts}][/color] [color={color}]{msg}[/color]'
        self._log_lines.append(line)
        if len(self._log_lines) > 300:
            self._log_lines = self._log_lines[-300:]
        Clock.schedule_once(self._flush_log, 0)

    def _flush_log(self, *_):
        self.log_lbl.text = '\n'.join(self._log_lines)
        Clock.schedule_once(lambda *_: setattr(self._scroll, 'scroll_y', 0), 0.05)

    def set_status(self, msg: str, rgb=(0.48, 0.52, 0.66)):
        def _do(*_):
            self.status_lbl.text  = msg
            self.status_lbl.color = (*rgb, 1)
        Clock.schedule_once(_do, 0)

    # ── Android permissions ───────────────────────────────────────────────────
    def _request_android_permissions(self):
        if platform != 'android':
            return
        perms = [
            Permission.INTERNET,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
        ]
        # MANAGE_EXTERNAL_STORAGE is needed on Android 11+ (API 30+)
        try:
            perms.append(Permission.MANAGE_EXTERNAL_STORAGE)
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
                'YouTubeMonitor::WakeLock',
            )
            self._wake_lock.acquire()
            self.log('Wake lock acquired — CPU stays on.', color='3dd68c')
        except Exception as exc:
            self.log(f'Wake lock error: {exc}', color='f5a623')

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
        """
        Download a static ffmpeg binary for Android arm64 if not already present.
        yt-dlp will be told where it lives via --ffmpeg-location.
        """
        if os.path.exists(FFMPEG_BIN):
            self.log(f'ffmpeg ready: {FFMPEG_BIN}')
            return

        self.log('Downloading ffmpeg binary (one-time, ~10 MB)…', color='f5a623')
        try:
            import tarfile, io
            tmp = FFMPEG_BIN + '.tar.xz'
            urllib.request.urlretrieve(FFMPEG_URL, tmp)
            with tarfile.open(tmp, 'r:xz') as tf:
                for member in tf.getmembers():
                    if member.name.endswith('/ffmpeg') and not member.isdir():
                        member.name = 'ffmpeg'
                        tf.extract(member, APP_DIR)
                        break
            os.remove(tmp)
            os.chmod(FFMPEG_BIN, 0o755)
            self.log('ffmpeg downloaded and ready.', color='3dd68c')
        except Exception as exc:
            self.log(f'ffmpeg download failed: {exc}', color='e05252')
            self.log('Recording may fail without ffmpeg.', color='f5a623')

    # ── Button handlers ───────────────────────────────────────────────────────
    def _on_start(self, *_):
        url = self.url_input.text.strip()
        if not url:
            self.set_status('Please enter a URL.', (0.87, 0.32, 0.32))
            return

        self._running = True
        self.start_btn.disabled  = True
        self.stop_btn.disabled   = False
        self.url_input.disabled  = True

        self.set_status('Monitor running…', (0.31, 0.43, 0.97))
        self._acquire_wake_lock()

        threading.Thread(
            target=self._monitor_loop, args=(url,), daemon=True
        ).start()

    def _on_stop(self, *_):
        self._running = False
        # Kill any in-flight yt-dlp process immediately
        if self._current_proc is not None:
            try:
                self._current_proc.terminate()
            except Exception:
                pass
        self._release_wake_lock()
        self.start_btn.disabled  = False
        self.stop_btn.disabled   = True
        self.url_input.disabled  = False
        self.set_status('Stopped.', (0.48, 0.52, 0.66))
        self.log('Monitor stopped by user.')

    # ── Monitor loop (background thread) ─────────────────────────────────────
    def _monitor_loop(self, url: str):
        live_url = resolve_live_url(url)
        self.log(f'Monitoring  → {url}')
        self.log(f'Check URL   → {live_url}')
        self.log(f'Save folder → {DOWNLOAD_DIR}')

        while self._running:
            self.set_status('Checking if live…', (0.31, 0.43, 0.97))
            self.log('Checking if stream is live…')

            is_live = self._check_live(live_url)
            if not self._running:
                break

            if not is_live:
                self.log(
                    f'Not live. Next check in {POLL_INTERVAL}s…',
                    color='f5a623',
                )
                self.set_status(
                    f'Not live — checking in {POLL_INTERVAL}s',
                    (0.96, 0.65, 0.14),
                )
                self._interruptible_sleep(POLL_INTERVAL)
                continue

            # ── Stream is live ────────────────────────────────────
            self.log('● Stream is LIVE — starting recording!', color='e05252')
            self.set_status('● Recording…', (0.87, 0.32, 0.32))
            self._record(live_url)

            if not self._running:
                break

            self.log(
                f'Recording finished. Next check in {POLL_INTERVAL}s…',
                color='3dd68c',
            )
            self.set_status(
                f'Stream ended — next check in {POLL_INTERVAL}s',
                (0.24, 0.84, 0.55),
            )
            self._interruptible_sleep(POLL_INTERVAL)

        self.log('Monitor loop exited.')

    def _interruptible_sleep(self, seconds: int):
        for _ in range(seconds):
            if not self._running:
                return
            time.sleep(1)

    # ── Live check ────────────────────────────────────────────────────────────
    def _check_live(self, url: str) -> bool:
        try:
            result = subprocess.run(
                [
                    'yt-dlp',
                    '--simulate',
                    '--quiet',
                    '--no-warnings',
                    '--no-playlist',
                    '--socket-timeout', '20',
                    url,
                ],
                capture_output=True,
                timeout=45,
            )
            return result.returncode == 0
        except Exception as exc:
            self.log(f'Check error: {exc}', color='f5a623')
            return False

    # ── Record ────────────────────────────────────────────────────────────────
    def _record(self, url: str):
        ts              = datetime.now().strftime('%d%m%Y_%H%M')
        output_template = os.path.join(DOWNLOAD_DIR, f'%(title)s_{ts}.%(ext)s')

        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--no-playlist',
            '--restrict-filenames',       # removes !, ?, # etc. — safe for Android storage
            '--no-part',                  # no .part temp files
            '--merge-output-format', 'mp4',
            '-o', output_template,
        ]

        # Use bundled ffmpeg if available
        if os.path.exists(FFMPEG_BIN):
            cmd += ['--ffmpeg-location', FFMPEG_BIN]

        cmd.append(url)

        try:
            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            for raw_line in self._current_proc.stdout:
                line = raw_line.strip()
                if line:
                    self.log(line)
                if not self._running:
                    self._current_proc.terminate()
                    break

            self._current_proc.wait()
            self.log(f'yt-dlp exited (code {self._current_proc.returncode})')

        except Exception as exc:
            self.log(f'Recording error: {exc}', color='e05252')
        finally:
            self._current_proc = None


if __name__ == '__main__':
    YouTubeMonitorApp().run()
