[app]
title = TikTok Indirici
package.name = tiktokindirici
package.domain = org.indirici
source.dir = .
source.include_exts = py,html,png
source.exclude_dirs = .github,bin,.buildozer
version = 1.0
icon.filename = %(source.dir)s/icon.png

# yt-dlp saf Python oldugu icin ayrica bir sey gerekmez.
requirements = python3,android,pyjnius,certifi,yt-dlp

orientation = portrait
fullscreen = 0

# Uygulama arayuzu, telefonun icinde calisan kucuk bir sunucuyu WebView'de gosterir.
p4a.bootstrap = webview
p4a.port = 8765

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
# Hedef surum 27: videolari Movies/TikTok klasorune dogrudan yazabilmek ve
# yerel sunucuya (http://127.0.0.1) ek ayar olmadan baglanabilmek icin.
android.api = 27
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 0
