import os, re, ssl, time, threading
from datetime import datetime
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.togglebutton import ToggleButton
from kivy.clock import Clock
from kivy.utils import platform
from kivy.metrics import dp, sp
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass
if platform == 'android':
    DOWNLOAD_DIR = '/storage/emulated/0/Download/StreamRecorder'
else:
    DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'StreamRecorder')
APP_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_BIN = os.path.join(APP_DIR, 'ffmpeg')
POLL_SECONDS = 60
FFMPEG_URL = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-android-arm64-gpl.tar.xz'
_CHANNEL_RE = re.compile(r'youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)(/live)?$')
def resolve_live_url(url):
    url = url.rstrip('/')
    if _CHANNEL_RE.search(url) and not url.endswith('/live'):
        return url + '/live'
    return url
class Card(BoxLayout):
    def __init__(self, bg_color=(0.13, 0.14, 0.20, 1), radius=14, **kwargs):
        super().__init__(**kwargs)
        self._bg = bg_color
        self._rad = radius
        self.bind(pos=self._draw, size=self._draw)
    def _draw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self._bg)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self._rad])
class StreamRecorderApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._running = False
        self._wake_lock = None
        self._log_lines = []
    def build(self):
        self.title = 'Stream Recorder'
        Window.clearcolor = (0.07, 0.08, 0.12, 1)
        root_scroll = ScrollView(size_hint=(1, 1))
        root = BoxLayout(orientation='vertical', padding=dp(16), spacing=dp(12), size_hint_y=None)
        root.bind(minimum_height=root.setter('height'))
        root_scroll.add_widget(root)
        header = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(12))
        icon_card = Card(bg_color=(0.28, 0.38, 0.95, 1), radius=12, size_hint=(None, None), size=(dp(48), dp(48)))
        icon_card.add_widget(Label(text='[b]SR[/b]', font_size=sp(16), markup=True, color=(1,1,1,1)))
        title_lbl = Label(text='Stream Recorder', font_size=sp(22), bold=True, color=(0.93, 0.94, 0.98, 1), halign='left', valign='middle')
        title_lbl.bind(size=title_lbl.setter('text_size'))
        header.add_widget(icon_card)
        header.add_widget(title_lbl)
        root.add_widget(header)
        mode_card = Card(size_hint_y=None, height=dp(86), padding=dp(12), spacing=dp(8), orientation='vertical')
        mode_title = Label(text='RECORDING MODE', font_size=sp(10), bold=True, color=(0.42, 0.48, 0.65, 1), size_hint_y=None, height=dp(16), halign='left', valign='middle')
        mode_title.bind(size=mode_title.setter('text_size'))
        toggle_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self.manual_btn = ToggleButton(text='Manual', group='mode', state='down', font_size=sp(13), bold=True, background_color=(0.28, 0.38, 0.95, 1), color=(1, 1, 1, 1))
        self.manual_btn.bind(on_press=lambda _: Clock.schedule_once(lambda __: self._apply_mode(), 0.05))
        self.auto_btn = ToggleButton(text='Auto-Monitor', group='mode', state='normal', font_size=sp(13), bold=True, background_color=(0.16, 0.18, 0.28, 1), color=(0.58, 0.64, 0.85, 1))
        self.auto_btn.bind(on_press=lambda _: Clock.schedule_once(lambda __: self._apply_mode(), 0.05))
        toggle_row.add_widget(self.manual_btn)
        toggle_row.add_widget(self.auto_btn)
        mode_card.add_widget(mode_title)
        mode_card.add_widget(toggle_row)
        root.add_widget(mode_card)
        rec_card = Card(size_hint_y=None, height=dp(158), padding=dp(14), spacing=dp(10), orientation='vertical')
        rec_title = Label(text='RECORD A STREAM', font_size=sp(10), bold=True, color=(0.42, 0.48, 0.65, 1), size_hint_y=None, height=dp(16), halign='left', valign='middle')
        rec_title.bind(size=rec_title.setter('text_size'))
        self.url_input = TextInput(hint_text='Paste YouTube URL here...', hint_text_color=(0.35, 0.40, 0.58, 1), foreground_color=(0.92, 0.93, 0.98, 1), background_color=(0.08, 0.09, 0.14, 1), cursor_color=(0.55, 0.65, 1, 1), multiline=False, size_hint_y=None, height=dp(48), font_size=sp(14), padding=[dp(14), dp(13)])
        self.action_btn = Button(text='Start Recording', background_color=(0.28, 0.38, 0.95, 1), color=(1, 1, 1, 1), font_size=sp(15), bold=True, size_hint_y=None, height=dp(52))
        self.action_btn.bind(on_press=self._on_action)
        rec_card.add_widget(rec_title)
        rec_card.add_widget(self.url_input)
        rec_card.add_widget(self.action_btn)
        root.add_widget(rec_card)
        status_card = Card(size_hint_y=None, height=dp(62), padding=[dp(14), dp(8)], orientation='vertical')
        self.status_lbl = Label(text='Ready', font_size=sp(15), bold=True, color=(0.35, 0.88, 0.60, 1), size_hint_y=None, height=dp(26), halign='left', valign='middle')
        self.status_lbl.bind(size=self.status_lbl.setter('text_size'))
        self.sub_lbl = Label(text='Waiting for input...', font_size=sp(11), color=(0.40, 0.44, 0.62, 1), size_hint_y=None, height=dp(20), halign='left', valign='middle')
        self.sub_lbl.bind(size=self.sub_lbl.setter('text_size'))
        status_card.add_widget(self.status_lbl)
        status_card.add_widget(self.sub_lbl)
        root.add_widget(status_card)
        dl_card = Card(size_hint_y=None, height=dp(210), padding=dp(14), spacing=dp(10), orientation='vertical')
        dl_hdr = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        dl_ttl = Label(text='DOWNLOADS', font_size=sp(10), bold=True, color=(0.42, 0.48, 0.65, 1), halign='left', valign='middle')
        dl_ttl.bind(size=dl_ttl.setter('text_size'))
        ref_btn = Button(text='Refresh', size_hint=(None, 1), width=dp(85), font_size=sp(12), background_color=(0.16, 0.18, 0.28, 1), color=(0.65, 0.70, 0.90, 1))
        ref_btn.bind(on_press=self._refresh_downloads)
        del_btn = Button(text='Delete All', size_hint=(None, 1), width=dp(95), font_size=sp(12), background_color=(0.50, 0.12, 0.12, 1), color=(1, 0.60, 0.60, 1))
        del_btn.bind(on_press=self._delete_all)
        dl_hdr.add_widget(dl_ttl)
        dl_hdr.add_widget(ref_btn)
        dl_hdr.add_widget(del_btn)
        self._dl_scroll = ScrollView(size_hint=(1, 1))
        self.dl_list = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))
        self.dl_list.bind(minimum_height=self.dl_list.setter('height'))
        self._dl_scroll.add_widget(self.dl_list)
        dl_card.add_widget(dl_hdr)
        dl_card.add_widget(self._dl_scroll)
        root.add_widget(dl_card)
        log_card = Card(size_hint_y=None, height=dp(190), padding=dp(14), spacing=dp(6), orientation='vertical')
        log_ttl = Label(text='ACTIVITY LOG', font_size=sp(10), bold=True, color=(0.42, 0.48, 0.65, 1), size_hint_y=None, height=dp(16), halign='left', valign='middle')
        log_ttl.bind(size=log_ttl.setter('text_size'))
        self._log_scroll = ScrollView(size_hint=(1, 1))
        self.log_lbl = Label(text='', font_size=sp(11), halign='left', valign='top', size_hint_y=None, markup=True, color=(0.70, 0.74, 0.90, 1))
        self.log_lbl.bind(texture_size=lambda i, v: setattr(i, 'height', max(v[1], dp(40))))
        self._log_scroll.add_widget(self.log_lbl)
        log_card.add_widget(log_ttl)
        log_card.add_widget(self._log_scroll)
        root.add_widget(log_card)
        p = Label(text='Saves to: ' + DOWNLOAD_DIR, font_size=sp(10), color=(0.28, 0.32, 0.48, 1), size_hint_y=None, height=dp(22), halign='left', valign='middle')
        p.bind(size=p.setter('text_size'))
        root.add_widget(p)
        self._request_permissions()
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        Clock.schedule_once(lambda _: self._ensure_ffmpeg_async(), 2)
        Clock.schedule_once(lambda _: self._refresh_downloads(), 1)
        return root_scroll
    def _apply_mode(self):
        if self._running:
            return
        if self.auto_btn.state == 'down':
            self.auto_btn.background_color = (0.28, 0.38, 0.95, 1)
            self.auto_btn.color = (1, 1, 1, 1)
            self.manual_btn.background_color = (0.16, 0.18, 0.28, 1)
            self.manual_btn.color = (0.58, 0.64, 0.85, 1)
            self.action_btn.text = 'Start Auto-Monitor'
        else:
            self.manual_btn.background_color = (0.28, 0.38, 0.95, 1)
            self.manual_btn.color = (1, 1, 1, 1)
            self.auto_btn.background_color = (0.16, 0.18, 0.28, 1)
            self.auto_btn.color = (0.58, 0.64, 0.85, 1)
            self.action_btn.text = 'Start Recording'
    def _on_action(self, *_):
        if self._running:
            self._stop()
            return
        url = self.url_input.text.strip()
        if not url:
            self.set_status('Paste a URL first', (0.95, 0.38, 0.25, 1))
            return
        self._running = True
        self.action_btn.text = 'Stop'
        self.action_btn.background_color = (0.72, 0.15, 0.15, 1)
        self.url_input.disabled = True
        self.auto_btn.disabled = True
        self.manual_btn.disabled = True
        self._acquire_wake_lock()
        if self.auto_btn.state == 'down':
            self.set_status('Auto-Monitor ON', (0.30, 0.68, 0.95, 1))
            self.set_sub('Checking every 60s...')
            threading.Thread(target=self._auto_loop, args=(url,), daemon=True).start()
        else:
            self.set_status('Recording...', (0.95, 0.28, 0.28, 1))
            self.set_sub('Recording - tap Stop to finish')
            threading.Thread(target=self._do_record, args=(url,), daemon=True).start()
    def _stop(self):
        self._running = False
        self._release_wake_lock()
        self.action_btn.disabled = False
        self.url_input.disabled = False
        self.auto_btn.disabled = False
        self.manual_btn.disabled = False
        self.set_status('Ready', (0.35, 0.88, 0.60, 1))
        self.set_sub('Stopped - waiting for input...')
        self._apply_mode()
        self._refresh_downloads()
    def _auto_loop(self, url):
        live_url = resolve_live_url(url)
        self.log('Monitoring: ' + live_url)
        while self._running:
            self.log('Checking live status...')
            if self._check_live(live_url):
                self.log('LIVE - recording!', 'e05252')
                self.set_status('Recording...', (0.95, 0.28, 0.28, 1))
                self._do_record(live_url)
                if not self._running:
                    break
                self.set_status('Auto-Monitor ON', (0.30, 0.68, 0.95, 1))
                self.log('Stream ended. Resuming checks...', '33cc88')
            else:
                self.log('Not live. Next check in 60s...', 'f5a623')
                self.set_sub('Not live - next check in 60s')
            self._isleep(POLL_SECONDS)
        self.log('Monitor stopped.')
    def _isleep(self, s):
        for _ in range(s):
            if not self._running:
                return
            time.sleep(1)
    def _check_live(self, url):
        try:
            import yt_dlp
            opts = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'socket_timeout': 20, 'simulate': True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return bool(info and info.get('is_live'))
        except Exception as e:
            self.log('Check error: ' + str(e), 'f5a623')
            return False
    def _do_record(self, url):
        try:
            import yt_dlp
            ts = datetime.now().strftime('%d%m%Y_%H%M')
            tpl = os.path.join(DOWNLOAD_DIR, '%(title)s_' + ts + '.%(ext)s')
            opts = {'outtmpl': tpl, 'quiet': False, 'no_warnings': True, 'noplaylist': True, 'merge_output_format': 'mp4', 'restrictfilenames': True, 'nopart': True, 'progress_hooks': [self._on_progress], 'logger': _Logger(self.log)}
            if os.path.exists(FFMPEG_BIN):
                opts['ffmpeg_location'] = FFMPEG_BIN
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            if self._running:
                self.log('Recording error: ' + str(e), 'e05252')
    def _on_progress(self, d):
        if d.get('status') == 'downloading':
            pct = d.get('_percent_str', '').strip()
            spd = d.get('_speed_str', '').strip()
            if pct:
                self.set_sub(pct + ' @ ' + spd)
        elif d.get('status') == 'finished':
            fn = os.path.basename(d.get('filename', ''))
            self.log('Saved: ' + fn, '33cc88')
            Clock.schedule_once(lambda _: self._refresh_downloads(), 0.5)
    def _refresh_downloads(self, *_):
        self.dl_list.clear_widgets()
        try:
            files = sorted([f for f in os.listdir(DOWNLOAD_DIR) if f.endswith('.mp4')], reverse=True)
        except Exception:
            files = []
        if not files:
            self.dl_list.add_widget(Label(text='No recordings yet', font_size=sp(12), color=(0.35, 0.40, 0.58, 1), size_hint_y=None, height=dp(40)))
            return
        for fn in files:
            row = BoxLayout(size_hint_y=None, height=dp(36), padding=[dp(10), 0])
            with row.canvas.before:
                Color(0.10, 0.11, 0.17, 1)
                RoundedRectangle(pos=row.pos, size=row.size, radius=[7])
            row.bind(pos=lambda w, _: self._rdraw(w), size=lambda w, _: self._rdraw(w))
            lbl = Label(text=fn, font_size=sp(12), color=(0.76, 0.80, 0.95, 1), halign='left', valign='middle')
            lbl.bind(size=lbl.setter('text_size'))
            row.add_widget(lbl)
            self.dl_list.add_widget(row)
    def _rdraw(self, w):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(0.10, 0.11, 0.17, 1)
            RoundedRectangle(pos=w.pos, size=w.size, radius=[7])
    def _delete_all(self, *_):
        try:
            for f in os.listdir(DOWNLOAD_DIR):
                if f.endswith('.mp4'):
                    os.remove(os.path.join(DOWNLOAD_DIR, f))
        except Exception:
            pass
        self._refresh_downloads()
        self.log('All recordings deleted.', 'f5a623')
    def log(self, msg, color='bcc2dc'):
        ts = datetime.now().strftime('%H:%M:%S')
        self._log_lines.append('[color=3a4060][' + ts + '][/color] [color=' + color + ']' + msg + '[/color]')
        if len(self._log_lines) > 300:
            self._log_lines = self._log_lines[-300:]
        Clock.schedule_once(self._flush_log, 0)
    def _flush_log(self, *_):
        self.log_lbl.text = '\n'.join(self._log_lines)
        Clock.schedule_once(lambda *_: setattr(self._log_scroll, 'scroll_y', 0), 0.05)
    def set_status(self, msg, color=(0.35, 0.88, 0.60, 1)):
        def _d(*_):
            self.status_lbl.text = msg
            self.status_lbl.color = color
        Clock.schedule_once(_d, 0)
    def set_sub(self, msg):
        Clock.schedule_once(lambda *_: setattr(self.sub_lbl, 'text', msg), 0)
    def _request_permissions(self):
        if platform != 'android':
            return
        request_permissions([Permission.INTERNET, Permission.WAKE_LOCK, Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])
    def _acquire_wake_lock(self):
        if platform != 'android':
            return
        try:
            PA = autoclass('org.kivy.android.PythonActivity')
            PM = autoclass('android.os.PowerManager')
            pm = PA.mActivity.getSystemService('power')
            self._wake_lock = pm.newWakeLock(PM.PARTIAL_WAKE_LOCK, 'StreamRecorder::WL')
            self._wake_lock.acquire()
        except Exception:
            pass
    def _release_wake_lock(self):
        try:
            if self._wake_lock and self._wake_lock.isHeld():
                self._wake_lock.release()
        except Exception:
            pass
        self._wake_lock = None
    def _ensure_ffmpeg_async(self):
        threading.Thread(target=self._ensure_ffmpeg, daemon=True).start()
    def _ensure_ffmpeg(self):
        if os.path.exists(FFMPEG_BIN):
            self.log('ffmpeg ready')
            return
        self.log('Downloading ffmpeg (~10 MB)...', 'f5a623')
        try:
            import tarfile, requests, certifi
            tmp = FFMPEG_BIN + '.tar.xz'
            r = requests.get(FFMPEG_URL, stream=True, verify=certifi.where(), timeout=60)
            r.raise_for_status()
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            with tarfile.open(tmp, 'r:xz') as tf:
                for m in tf.getmembers():
                    if m.name.endswith('/ffmpeg') and not m.isdir():
                        m.name = 'ffmpeg'
                        tf.extract(m, APP_DIR)
                        break
            os.remove(tmp)
            os.chmod(FFMPEG_BIN, 0o755)
            self.log('ffmpeg ready!', '33cc88')
        except Exception as e:
            self.log('ffmpeg failed: ' + str(e), 'e05252')
class _Logger:
    def __init__(self, fn):
        self._fn = fn
    def debug(self, m):
        if not m.startswith('[debug]'):
            self._fn(m)
    def info(self, m):
        self._fn(m)
    def warning(self, m):
        self._fn('[warn] ' + m, 'f5a623')
    def error(self, m):
        self._fn('[err] ' + m, 'e05252')
if __name__ == '__main__':
    StreamRecorderApp().run()
