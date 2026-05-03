[app]
title = Stream Recorder
package.name = streamrecorder
package.domain = com.streamrecorder
version = 1.0
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
requirements = python3,kivy==2.2.1,pyjnius,requests,certifi,urllib3,idna,charset-normalizer
android.minapi = 21
android.api = 31
android.ndk = 23b
android.ndk_api = 21
android.archs = arm64-v8a
android.enable_androidx = True
android.permissions = INTERNET,WAKE_LOCK,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
orientation = portrait
fullscreen = 0
android.accept_sdk_license = True
log_level = 2

[buildozer]
warn_on_root = 1
