# -*- coding: utf-8 -*-
"""
Derlemeden once python-for-android'in WebView sablonuna 'usesCleartextTraffic' ekler.
Yeni Android surumleri, uygulamanin telefonun icindeki yerel sunucusuna (http://127.0.0.1)
baglanmasini ancak bu ayarla kabul eder.
"""
import glob
import os
import re
import subprocess
import sys

KOK = os.path.join(".buildozer", "android", "platform", "python-for-android")

if not os.path.isdir(KOK):
    os.makedirs(os.path.dirname(KOK), exist_ok=True)
    subprocess.check_call(["git", "clone", "--branch", "master",
                           "https://github.com/kivy/python-for-android.git", KOK])

sablonlar = glob.glob(os.path.join(KOK, "pythonforandroid", "bootstraps", "webview", "build", "templates",
                                   "AndroidManifest*.xml"))
if not sablonlar:
    print("HATA: webview sablonu bulunamadi")
    sys.exit(1)

for yol in sablonlar:
    with open(yol, encoding="utf-8") as f:
        s = f.read()
    if "usesCleartextTraffic" in s:
        yeni = re.sub(r'android:usesCleartextTraffic="[^"]*"', 'android:usesCleartextTraffic="true"', s)
    else:
        yeni, n = re.subn(r"<application", '<application android:usesCleartextTraffic="true"', s, count=1)
        if n == 0:
            print("HATA: <application> etiketi bulunamadi:", yol)
            sys.exit(1)
    with open(yol, "w", encoding="utf-8") as f:
        f.write(yeni)
    print("yamalandi:", yol)
    for satir in yeni.splitlines():
        if "application" in satir or "Cleartext" in satir:
            print("   ", satir.strip())
