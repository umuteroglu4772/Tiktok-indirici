[app]
title = TikTok Indirici
package.name = tiktokindirici
package.domain = org.indirici
source.dir = .
source.include_exts = py,html,png
source.exclude_dirs = .github,bin,.buildozer
version = 1.1
icon.filename = %(source.dir)s/icon.png

# yt-dlp saf Python oldugu icin ayrica bir sey gerekmez.
requirements = python3,android,pyjnius,certifi,yt-dlp

orientation = portrait
fullscreen = 0

# Uygulama arayuzu, telefonun icinde calisan kucuk bir sunucuyu WebView'de gosterir.
p4a.bootstrap = webview
p4a.port = 8765

# MANAGE_EXTERNAL_STORAGE: videolari Movies/TikTok klasorune kaydedebilmek icin
# POST_NOTIFICATIONS: "indirme bitti" bildirimi icin
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,POST_NOTIFICATIONS
# Hedef surum yeterince yeni olmali (Play Protect "eski surum" uyarisi vermesin).
# Derleme akisi bu degeri 34 ve 33 olarak iki kez dener.
android.api = 34
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 0
