[app]

# ── Identity ──────────────────────────────────────────────────────────────────
title           = YouTube Live Monitor
package.name    = youtubelivemonitor
package.domain  = com.youtubelivemonitor
version         = 1.0

# ── Source ────────────────────────────────────────────────────────────────────
source.dir      = .
source.include_exts = py,png,jpg,kv,atlas

# ── Entry point ───────────────────────────────────────────────────────────────
# main.py in the project root is the default; nothing extra needed.

# ── Python requirements ───────────────────────────────────────────────────────
# All installed via pip inside the APK.
# Note: ffmpeg binary is downloaded at first launch by main.py itself.
requirements =
    python3,
    kivy==2.3.0,
    pyjnius,
    yt-dlp,
    requests,
    websockets,
    pycryptodome,
    certifi,
    charset-normalizer,
    idna,
    urllib3,
    mutagen,
    brotli

# ── Android build settings ────────────────────────────────────────────────────
android.minapi         = 21
android.api            = 34
android.ndk            = 25c
android.ndk_api        = 21
android.archs          = arm64-v8a

# Enable gradle for modern API targets
android.enable_androidx = True
android.gradle_dependencies =

# ── Permissions ───────────────────────────────────────────────────────────────
# WAKE_LOCK keeps the CPU alive during background recording.
# MANAGE_EXTERNAL_STORAGE is required on Android 11+ to write to Downloads.
android.permissions =
    INTERNET,
    WAKE_LOCK,
    FOREGROUND_SERVICE,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE,
    MANAGE_EXTERNAL_STORAGE

# ── Orientation & window ──────────────────────────────────────────────────────
orientation     = portrait
fullscreen      = 0

# ── Icons & splash (replace with your own images) ────────────────────────────
# icon.filename   = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png

# ── Build type ────────────────────────────────────────────────────────────────
# Use 'release' when signing for distribution; 'debug' for testing.
android.debug = 1

# ── p4a (python-for-android) ──────────────────────────────────────────────────
# Use the latest stable p4a for best Python 3.11 + arm64 support.
p4a.branch      = v2024.01.21

# ── Log level (0 = minimal, 2 = verbose) ─────────────────────────────────────
log_level = 1

# ── Buildozer cache (speeds up repeated builds) ───────────────────────────────
[buildozer]
warn_on_root = 1


# ══════════════════════════════════════════════════════════════════════════════
#  HOW TO BUILD
# ══════════════════════════════════════════════════════════════════════════════
#
#  Prerequisites (Ubuntu / WSL2 / Termux recommended):
#
#    sudo apt update && sudo apt install -y \
#        git zip unzip openjdk-17-jdk python3 python3-pip \
#        autoconf libtool pkg-config libffi-dev \
#        libssl-dev python3-dev build-essential
#
#    pip install buildozer cython
#
#  First build (downloads Android SDK/NDK automatically, ~10–20 min):
#
#    cd kivy-app
#    buildozer android debug
#
#  Output APK will be at:
#    kivy-app/bin/youtubelivemonitor-1.0-debug.apk
#
#  Install on your phone (USB debugging on):
#    adb install bin/youtubelivemonitor-1.0-debug.apk
#
#  Or copy the APK to your phone and open it to sideload.
#
#  FIRST LAUNCH:
#    - Grant Storage + Internet permissions when prompted.
#    - ffmpeg (~10 MB) downloads automatically in the background.
#    - Paste a YouTube channel URL (e.g. youtube.com/@ChannelName).
#    - Press Start Monitor. The app checks every 60 seconds.
#    - Files save to: /storage/emulated/0/Download/YouTubeMonitor/
#
# ══════════════════════════════════════════════════════════════════════════════
