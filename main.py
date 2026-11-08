# -*- coding: utf-8 -*-
"""
Başlatıcı. Uygulamanın asıl kodu uygulama.py + sayfa.html dosyalarındadır.

Her açılışta bu iki dosyanın en yenisi GitHub deposundan arka planda indirilir ve BİR SONRAKİ
açılışta kullanılır. Böylece kodu değiştirince APK'yı yeniden derlemek gerekmez; deponun
ana klasörüne uygulama.py ve sayfa.html yüklemek yeterlidir.
İndirme başarısız olursa ya da dosya bozuksa uygulamanın içindeki sürüm çalışır.
"""

import hashlib
import importlib.util
import os
import ssl
import sys
import threading
import traceback
import urllib.request

DEPO = "umuteroglu4772/Tiktok-indirici"
DAL = "main"
TABAN = os.environ.get("TT_KOD_TABAN") or ("https://raw.githubusercontent.com/%s/%s/" % (DEPO, DAL))
DOSYALAR = ("uygulama.py", "sayfa.html")
BURASI = os.path.dirname(os.path.abspath(__file__))
ONBELLEK = os.path.join(os.environ.get("ANDROID_PRIVATE") or BURASI, "guncel_kod")


def sha(yol):
    with open(yol, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def paket_imzasi():
    """Uygulamanın içindeki uygulama.py'nin imzası (APK yenilenince önbellek geçersiz olsun diye)."""
    for ad in ("uygulama.py", "uygulama.pyc"):
        yol = os.path.join(BURASI, ad)
        if os.path.exists(yol):
            return sha(yol)
    return ""


def onbellek_hazir():
    try:
        with open(os.path.join(ONBELLEK, "imza")) as f:
            if f.read().strip() != paket_imzasi():
                return False
        return all(os.path.exists(os.path.join(ONBELLEK, a)) for a in DOSYALAR)
    except Exception:
        return False


def ssl_baglami():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def guncelle():
    """Arka planda en yeni kodu indirir; ancak sağlam görünüyorsa önbelleğe yazar."""
    try:
        ctx = ssl_baglami()
        yeni = {}
        for ad in DOSYALAR:
            istek = urllib.request.Request(TABAN + ad, headers={"User-Agent": "TikTokIndirici"})
            with urllib.request.urlopen(istek, timeout=20, context=ctx) as r:
                yeni[ad] = r.read()
        compile(yeni["uygulama.py"].decode("utf-8"), "uygulama.py", "exec")      # sözdizimi sağlam mı?
        if b"<html" not in yeni["sayfa.html"][:3000].lower():
            raise ValueError("sayfa.html bozuk")
        os.makedirs(ONBELLEK, exist_ok=True)
        for ad, veri in yeni.items():
            gecici = os.path.join(ONBELLEK, ad + ".tmp")
            with open(gecici, "wb") as f:
                f.write(veri)
            os.replace(gecici, os.path.join(ONBELLEK, ad))
        with open(os.path.join(ONBELLEK, "imza"), "w") as f:
            f.write(paket_imzasi())
    except Exception:
        pass


def modul_yukle(yol, ad):
    spec = importlib.util.spec_from_file_location(ad, yol)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def baslat():
    if onbellek_hazir():
        try:
            modul_yukle(os.path.join(ONBELLEK, "uygulama.py"), "uygulama_guncel").main()
            return
        except Exception:
            traceback.print_exc()   # güncel kod çalışmadıysa içindeki sürüme dön
    if BURASI not in sys.path:
        sys.path.insert(0, BURASI)
    import uygulama
    uygulama.main()


if os.environ.get("TT_GUNCELLE", "1") != "0" or os.environ.get("TT_KOD_TABAN"):
    threading.Thread(target=guncelle, daemon=True).start()
baslat()
