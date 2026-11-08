# -*- coding: utf-8 -*-
"""
TikTok İndirici - Android (APK) sürümü.

Uygulama açılınca telefonun içinde küçük bir web sunucusu çalışır (sadece telefonun kendisi
erişebilir) ve arayüz (sayfa.html) uygulamanın içindeki WebView'de gösterilir.
İndirme işini yt-dlp yapar. Videolar telefonda  Movies/TikTok  klasörüne kaydedilir.
"""

import json
import mimetypes
import os
import queue
import re
import secrets
import ssl
import sys
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

KOD_SURUMU = "1.5"   # kod her güncellendiğinde değişir (uygulamanın üstünde görünür)
PORT = 8765
ANDROID = "ANDROID_ARGUMENT" in os.environ                 # Android'de miyiz?
GUNCELLE = os.environ.get("TT_GUNCELLE", "1") != "0"        # açılışta yt-dlp'yi güncelle
UYGULAMA = Path(__file__).resolve().parent

KILIT = threading.Lock()
HAZIR = threading.Event()
DUR = threading.Event()
KUYRUK = queue.Queue()
KAYITLAR = []
DURUM = {"calisiyor": False, "yuzde": 0.0, "bilgi": "", "dosya": "yt-dlp hazırlanıyor...", "mesaj": ""}
YT = {"modul": None, "surum": ""}
KLASOR_SON = {"yol": None}

BIRIMLER_MB = 1048576
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
KULLANICI_RE = re.compile(r"^@?[A-Za-z0-9._]{1,40}$")
UA = {"User-Agent": "TikTokIndirici"}


# ---------------- Yardımcılar ----------------

def mb_yaz(bayt):
    if bayt >= 1024 ** 3:
        return "%.2f GB" % (bayt / 1024 ** 3)
    return "%.1f MB" % (bayt / BIRIMLER_MB)


def sure_yaz(sn):
    sn = int(sn)
    return "%02d:%02d" % (sn // 60, sn % 60)


def veri_klasoru():
    d = Path(os.environ.get("ANDROID_PRIVATE") or (Path.home() / ".tiktok_indirici"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def girdiyi_coz(metin):
    """Sadece http(s) linkleri veya kullanıcı adı kabul edilir (başka bir şey yt-dlp'ye gitmez)."""
    parcalar = metin.split()
    if not parcalar or len(parcalar) > 30:
        raise ValueError("Önce bir link veya kullanıcı adı yaz.")
    if all(URL_RE.match(x) for x in parcalar):
        return ("link", parcalar)
    if len(parcalar) == 1 and KULLANICI_RE.match(parcalar[0]):
        return ("kullanici", parcalar)
    raise ValueError("Geçerli bir link (https://...) ya da kullanıcı adı yaz.")


def ssl_baglami():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ---------------- Depolama ve izin ----------------

IZIN = {"gerek": False}   # True: video galeriye kopyalanamadı, uygulamanın kendi klasöründe kaldı
TANI = []                 # ekranın altında "Sorun bilgisi" olarak gösterilir (hata ayıklama için)


def tani(yer, e):
    m = yer + ": " + type(e).__name__ + ": " + str(e)[:140]
    if m not in TANI:
        TANI.append(m)
        del TANI[:-6]


ETKINLIK = {"a": None}
ONYUKLE = ["org.kivy.android.PythonActivity", "android.content.Intent", "android.provider.Settings", "android.net.Uri",
           "android.os.Environment", "android.media.MediaScannerConnection", "android.content.ContentValues",
           "android.provider.MediaStore$MediaColumns", "android.provider.MediaStore$Video$Media",
           "java.io.FileInputStream", "android.os.FileUtils", "android.os.Build$VERSION", "android.content.Context",
           "android.app.NotificationManager", "android.app.NotificationChannel", "android.app.Notification$Builder",
           "android.app.PendingIntent"]


def android_hazirla():
    """Ana iş parçacığında çağrılır: Java sınıflarını önceden yükler.
    (Python'un diğer iş parçacıkları uygulama sınıflarını kendi başına bulamayabilir; önbellekten kullanır.)"""
    if not ANDROID:
        return
    try:
        from jnius import autoclass
    except Exception as e:
        tani("jnius", e)
        return
    for ad in ONYUKLE:
        try:
            autoclass(ad)
        except Exception as e:
            tani("yukle " + ad.split(".")[-1], e)
    try:
        ETKINLIK["a"] = autoclass("org.kivy.android.PythonActivity").mActivity
    except Exception as e:
        tani("etkinlik", e)


def aktivite():
    """Uygulamanın Android etkinliği (Activity)."""
    if ETKINLIK["a"] is not None:
        return ETKINLIK["a"]
    from jnius import autoclass
    try:
        from android.config import ACTIVITY_CLASS_NAME
    except Exception:
        ACTIVITY_CLASS_NAME = "org.kivy.android.PythonActivity"
    a = autoclass(ACTIVITY_CLASS_NAME).mActivity
    if a is None:
        try:
            from android import mActivity as a2
            a = a2
        except Exception:
            pass
    if a is None:
        raise RuntimeError("Activity bulunamadı")
    return a


def izin_iste():
    """Normal izin pencereleri (bildirim + eski Android'ler için depolama)."""
    if not ANDROID:
        return
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE,
                             "android.permission.POST_NOTIFICATIONS"])
    except Exception as e:
        tani("izin_iste", e)


def tum_dosya_izni_iste():
    """İsteğe bağlı: 'Tüm dosyalara erişim' ayar ekranını açar. Açabildiyse True döner."""
    if not ANDROID:
        return False
    try:
        from jnius import autoclass
        niyet = autoclass("android.content.Intent")
        ayar = autoclass("android.provider.Settings")
        uri = autoclass("android.net.Uri")
        etkinlik = aktivite()
        try:
            i = niyet(ayar.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, uri.parse("package:" + etkinlik.getPackageName()))
            etkinlik.startActivity(i)
        except Exception:
            etkinlik.startActivity(niyet(ayar.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
        return True
    except Exception as e:
        tani("tum_dosya_izni", e)
        return False


def yazilabilir(d):
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".yazma_testi"
        t.write_text("1")
        t.unlink()
        return True
    except Exception:
        return False


def galeri_klasoru():
    return Path(os.environ.get("EXTERNAL_STORAGE") or "/sdcard") / "Movies" / "TikTok"


def harici_klasor():
    """İzin gerektirmeyen, uygulamaya ait klasör (galeriye kopyalanmadan önce videolar buraya iner)."""
    try:
        d = aktivite().getExternalFilesDir(None)
        if d is not None:
            return Path(str(d.getAbsolutePath())) / "TikTok"
    except Exception as e:
        tani("harici_klasor", e)
    # jnius çalışmadıysa yolu elle kur: <depolama>/Android/data/<paket>/files
    try:
        parcalar = Path(os.environ.get("ANDROID_PRIVATE", "")).parts   # ('/', 'data', 'user', '0', '<paket>', 'files')
        paket = parcalar[4]
        d = Path(os.environ.get("EXTERNAL_STORAGE") or "/sdcard") / "Android" / "data" / paket / "files" / "TikTok"
        if yazilabilir(d):
            return d
    except Exception as e:
        tani("harici_yol", e)
    return Path(os.environ.get("ANDROID_PRIVATE", ".")) / "TikTok"


def klasor_bul():
    """Videoların ineceği klasör. Galeri klasörüne doğrudan yazılabiliyorsa orası, değilse uygulamanın kendi klasörü."""
    if not ANDROID:
        d = Path.home() / "Downloads" / "TikTok"
        d.mkdir(parents=True, exist_ok=True)
        KLASOR_SON["yol"] = d
        return d
    d = galeri_klasoru()
    if not yazilabilir(d):
        d = harici_klasor()
        d.mkdir(parents=True, exist_ok=True)
    KLASOR_SON["yol"] = d
    return d


def medya_tara(yol):
    """Doğrudan galeri klasörüne inen videonun galeride görünmesini sağlar."""
    if not ANDROID:
        return
    try:
        from jnius import autoclass
        autoclass("android.media.MediaScannerConnection").scanFile(aktivite(), [yol], None, None)
    except Exception as e:
        tani("medya_tara", e)


def galeriye_kopyala(yol):
    """Videoyu izin istemeden Movies/TikTok'a kopyalar (MediaStore, Android 10+). Başarılıysa True."""
    try:
        import mimetypes as mt
        from jnius import autoclass
        etkinlik = aktivite()
        cozucu = etkinlik.getContentResolver()
        deger = autoclass("android.content.ContentValues")()
        kolon = autoclass("android.provider.MediaStore$MediaColumns")
        deger.put(kolon.DISPLAY_NAME, os.path.basename(yol))
        deger.put(kolon.MIME_TYPE, mt.guess_type(yol)[0] or "video/mp4")
        deger.put(kolon.RELATIVE_PATH, "Movies/TikTok")
        uri = cozucu.insert(autoclass("android.provider.MediaStore$Video$Media").EXTERNAL_CONTENT_URI, deger)
        if uri is None:
            raise RuntimeError("MediaStore kaydı açılamadı")
        cikis = cozucu.openOutputStream(uri)
        giris = autoclass("java.io.FileInputStream")(yol)
        try:
            try:
                autoclass("android.os.FileUtils").copy(giris, cikis)
            except Exception as e1:
                tani("FileUtils", e1)
                with open(yol, "rb") as f:          # elle kopyala
                    while True:
                        parca = f.read(262144)
                        if not parca:
                            break
                        cikis.write(parca, 0, len(parca))
        finally:
            giris.close()
            cikis.close()
        return True
    except Exception as e:
        tani("galeriye_kopyala", e)
        return False


def bildirim_gonder(baslik, metin):
    """Telefonun bildirim çubuğuna 'indirme bitti' bildirimi gönderir."""
    if not ANDROID:
        return
    try:
        from jnius import autoclass, cast
        etkinlik = aktivite()
        surum = autoclass("android.os.Build$VERSION").SDK_INT
        baglam = autoclass("android.content.Context")
        yonetici = cast("android.app.NotificationManager", etkinlik.getSystemService(baglam.NOTIFICATION_SERVICE))
        yap = autoclass("android.app.Notification$Builder")
        kanal = "indirmeler"
        if surum >= 26:
            kanal_sinifi = autoclass("android.app.NotificationChannel")
            yonetici.createNotificationChannel(kanal_sinifi(kanal, "Indirmeler", 3))
            b = yap(etkinlik, kanal)
        else:
            b = yap(etkinlik)
        b.setSmallIcon(etkinlik.getApplicationInfo().icon)
        b.setContentTitle(baslik)
        b.setContentText(metin)
        b.setAutoCancel(True)
        niyet = etkinlik.getPackageManager().getLaunchIntentForPackage(etkinlik.getPackageName())
        bekleyen = autoclass("android.app.PendingIntent")
        bayrak = bekleyen.FLAG_UPDATE_CURRENT | (bekleyen.FLAG_IMMUTABLE if surum >= 23 else 0)
        b.setContentIntent(bekleyen.getActivity(etkinlik, 0, niyet, bayrak))
        yonetici.notify(int(time.time() * 1000) % 1000000, b.build())
    except Exception as e:
        tani("bildirim", e)


# ---------------- yt-dlp'yi hazırla ve güncelle ----------------

def son_surum_etiketi(ctx):
    """yt-dlp'nin en yeni sürüm numarasını bulur (önce github.com yönlendirmesi, olmazsa API)."""
    for _ in range(2):
        try:
            istek = urllib.request.Request("https://github.com/yt-dlp/yt-dlp/releases/latest", headers=UA, method="HEAD")
            with urllib.request.urlopen(istek, timeout=12, context=ctx) as r:
                son = r.geturl().rstrip("/").split("/")[-1]
            if re.match(r"^\d[\d.]*\d$", son):
                return son
        except Exception:
            pass
        try:
            istek = urllib.request.Request("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", headers=UA)
            with urllib.request.urlopen(istek, timeout=12, context=ctx) as r:
                return json.load(r)["tag_name"]
        except Exception:
            time.sleep(2)
    raise ValueError("GitHub yanıt vermedi")


def yt_dlp_guncelle_indir():
    """GitHub'daki en yeni yt-dlp'yi indirir (uygulamanın kendi klasörüne). Hata olursa kısa metin döner."""
    sd = veri_klasoru()
    zipapp, etiket = sd / "yt-dlp-guncel", sd / "yt-dlp-guncel.etiket"
    try:
        ctx = ssl_baglami()
        tag = son_surum_etiketi(ctx)
        eski = etiket.read_text().strip() if etiket.exists() else ""
        if tag != eski or not zipapp.exists():
            url = "https://github.com/yt-dlp/yt-dlp/releases/download/%s/yt-dlp" % tag
            gecici = sd / "yt-dlp-gecici"
            for deneme in range(3):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40, context=ctx) as r, \
                            open(gecici, "wb") as f:
                        while True:
                            parca = r.read(65536)
                            if not parca:
                                break
                            f.write(parca)
                    break
                except Exception:
                    if deneme == 2:
                        raise
                    time.sleep(3)
            if not (zipfile.is_zipfile(gecici) and gecici.stat().st_size > 500000):
                raise ValueError("indirilen dosya bozuk")
            os.replace(gecici, zipapp)
            etiket.write_text(tag)
        return ""
    except Exception as e:
        return "güncelleme alınamadı, bir sonraki açılışta tekrar denenecek"


def yt_dlp_yukle():
    """yt-dlp'yi içe aktarır. (sürüm, uyarı) döner."""
    uyari = ""
    if GUNCELLE:
        sonuc = {"u": ""}
        is_parcacigi = threading.Thread(target=lambda: sonuc.update(u=yt_dlp_guncelle_indir()), daemon=True)
        is_parcacigi.start()
        is_parcacigi.join(timeout=15)   # 15 sn'de bitmezse içindeki/önceki sürümle devam, indirme arka planda sürer
        uyari = sonuc["u"]
    zipapp = veri_klasoru() / "yt-dlp-guncel"
    if zipapp.exists() and "yt_dlp" not in sys.modules:
        sys.path.insert(0, str(zipapp))
    try:
        import yt_dlp
        from yt_dlp.version import __version__
    except Exception:
        # indirilen sürüm bozuksa uygulamanın içindekine dön
        for ad in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
            del sys.modules[ad]
        if str(zipapp) in sys.path:
            sys.path.remove(str(zipapp))
        import yt_dlp
        from yt_dlp.version import __version__
        uyari = uyari or "güncel sürüm yüklenemedi, uygulamadaki sürüm kullanılıyor"
    YT["modul"], YT["surum"] = yt_dlp, __version__
    return __version__, uyari


def hazirla():
    try:
        surum, uyari = yt_dlp_yukle()
        mesaj = "yt-dlp hazır (" + surum + ")" + ("  -  " + uyari if uyari else "")
        dosya = "Hazır"
    except Exception as e:
        mesaj, dosya = "yt-dlp yüklenemedi: " + str(e)[:120], "Hata"
    with KILIT:
        DURUM.update(dosya=dosya, mesaj=mesaj)
    HAZIR.set()


# ---------------- Kapak resmi ve kayıtlar ----------------

def kapak_bul(video_yolu):
    p = Path(video_yolu)
    for klasor in (p.parent / "kapaklar", p.parent):
        try:
            for f in klasor.iterdir():
                # TikTok kapakları .image gibi garip uzantılarla gelebilir; uzantıya bakmıyoruz
                if f.is_file() and f.stem == p.stem and f != p:
                    return str(f)
        except OSError:
            pass
    return None


def kayit_ekle(yol, kapak=None):
    with KILIT:
        if any(k["yol"] == yol for k in KAYITLAR):
            return
    ad = os.path.basename(yol)
    m = re.match(r"^(.*)_(\d{4})(\d{2})(\d{2})_\d+\.\w+$", ad)
    if m:
        baslik = "@" + m.group(1)
        bilgi = m.group(4) + "." + m.group(3) + "." + m.group(2)
    else:
        baslik, bilgi = ad, ""
    try:
        bilgi = (bilgi + "   •   " if bilgi else "") + mb_yaz(os.path.getsize(yol))
    except OSError:
        pass
    kayit = {"id": secrets.token_hex(4), "yol": yol, "kapak": kapak or kapak_bul(yol), "baslik": baslik, "bilgi": bilgi}
    with KILIT:
        KAYITLAR.append(kayit)


def kayit_bul(kimlik):
    with KILIT:
        for k in KAYITLAR:
            if k["id"] == kimlik:
                return dict(k)
    return None


def kayit_tasi(kimlik, yon):
    with KILIT:
        for i, k in enumerate(KAYITLAR):
            if k["id"] == kimlik:
                j = i + yon
                if 0 <= j < len(KAYITLAR):
                    KAYITLAR[i], KAYITLAR[j] = KAYITLAR[j], KAYITLAR[i]
                break


# ---------------- İndirme ----------------

class Kayitci:
    """yt-dlp'nin yazdıklarını yakalar; hata mesajı arayüzde gösterilir."""

    def debug(self, m):
        pass

    def info(self, m):
        pass

    def warning(self, m):
        pass

    def error(self, m):
        with KILIT:
            DURUM["mesaj"] = str(m)[:200]


def ilerleme(d):
    if DUR.is_set():
        iptal = getattr(YT["modul"].utils, "DownloadCancelled", Exception)
        raise iptal("durduruldu")
    if d.get("status") != "downloading":
        return
    toplam = d.get("total_bytes") or d.get("total_bytes_estimate")
    inen = d.get("downloaded_bytes") or 0
    y = min(100.0, inen * 100.0 / toplam) if toplam else 0.0
    parca = [mb_yaz(inen) + (" / " + mb_yaz(toplam) if toplam else "")]
    if d.get("speed"):
        parca.append(mb_yaz(d["speed"]) + "/s")
    if d.get("eta") is not None:
        parca.append("kalan " + sure_yaz(d["eta"]))
    with KILIT:
        DURUM.update(yuzde=y, bilgi="   •   ".join(parca),
                     dosya="İndiriliyor: " + os.path.basename(d.get("filename") or ""))


def bitti_kancasi(yol):
    kapak = kapak_bul(yol)
    son_yol, konum = yol, str(Path(yol).parent)
    if ANDROID:
        if str(yol).startswith(str(galeri_klasoru())):      # doğrudan galeri klasörüne indi
            medya_tara(yol)
            IZIN["gerek"] = False
            konum = "Movies/TikTok"
        elif galeriye_kopyala(yol):                          # izinsiz yol: MediaStore ile galeriye kopyala
            IZIN["gerek"] = False
            konum = "Movies/TikTok"
            genel = galeri_klasoru() / os.path.basename(yol)
            try:                                              # galerideki kopya okunabiliyorsa içerideki kopyayı sil
                with open(genel, "rb") as f:
                    f.read(1)
                os.remove(yol)
                son_yol = str(genel)
            except Exception:
                pass
        else:
            IZIN["gerek"] = True
            konum = "galeriye kopyalanamadı, uygulama klasöründe"
    kayit_ekle(son_yol, kapak)
    bildirim_gonder("İndirme tamamlandı ✔", os.path.basename(yol) + "  →  " + konum)
    try:
        boyut = os.path.getsize(son_yol)
        bilgi = mb_yaz(boyut) + " / " + mb_yaz(boyut)
    except OSError:
        bilgi = ""
    with KILIT:
        DURUM.update(yuzde=100.0, bilgi=bilgi, dosya="Tamamlandı: " + os.path.basename(yol) + "  (" + konum + ")")


def indir(tur, parcalar):
    yd = YT["modul"]
    if yd is None:
        with KILIT:
            DURUM.update(dosya="Hata", mesaj="yt-dlp yüklenemedi, uygulamayı kapatıp yeniden aç.")
        return
    kok = klasor_bul()
    if tur == "link":
        hedef, linkler = kok, parcalar
    else:
        kullanici = parcalar[0].lstrip("@")
        hedef, linkler = kok / ("tiktok_" + kullanici), ["https://www.tiktok.com/@" + kullanici]
    kapaklar = hedef / "kapaklar"
    try:
        kapaklar.mkdir(parents=True, exist_ok=True)
        (kapaklar / ".nomedia").touch()  # kapak resimleri galeride görünmesin
    except OSError:
        pass
    sablon = "%(uploader)s_%(upload_date)s_%(id)s.%(ext)s"
    secenek = {
        "outtmpl": {"default": str(hedef / sablon), "thumbnail": str(kapaklar / sablon)},
        "writethumbnail": True,
        "ignoreerrors": True,
        "nooverwrites": True,
        "noprogress": True,
        "retries": 5,
        "socket_timeout": 30,
        "logger": Kayitci(),
        "progress_hooks": [ilerleme],
        "post_hooks": [bitti_kancasi],
    }
    if tur == "kullanici":  # profil indirmede daha önce inenleri atla
        secenek["download_archive"] = str(hedef / "indirilenler.txt")
    kod = 1
    try:
        with yd.YoutubeDL(secenek) as ydl:
            kod = ydl.download(linkler)
    except Exception as e:
        if not DUR.is_set():
            with KILIT:
                DURUM["mesaj"] = "HATA: " + str(e)[:150]
    with KILIT:
        if DUR.is_set():
            DURUM["dosya"] = "Durduruldu"
        elif kod == 0:
            DURUM["dosya"] = "Bitti ✔️"
            DURUM["mesaj"] = ""
        else:
            DURUM["dosya"] = "Durdu veya hata oluştu (ayrıntı aşağıda)"
    DUR.clear()


def isci():
    HAZIR.wait()
    while True:
        tur, parcalar = KUYRUK.get()
        with KILIT:
            DURUM.update(calisiyor=True, yuzde=0.0, bilgi="", dosya="Başlıyor...", mesaj="")
        try:
            indir(tur, parcalar)
        except Exception as e:
            with KILIT:
                DURUM.update(dosya="Hata", mesaj=str(e)[:200])
        with KILIT:
            DURUM["calisiyor"] = False


def durdur():
    try:
        while True:
            KUYRUK.get_nowait()
    except queue.Empty:
        pass
    with KILIT:
        calisiyor = DURUM["calisiyor"]
    if calisiyor:
        DUR.set()


# ---------------- Web sunucusu (sadece telefonun kendisi bağlanır) ----------------

def resim_turu(b):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


class Isleyici(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _gonder(self, kod, veri, tur, ek=None):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (ek or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(veri)

    def _json(self, veri, kod=200):
        self._gonder(kod, json.dumps(veri, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _dosya(self, yol, ad, izle):
        try:
            boyut = os.path.getsize(yol)
            f = open(yol, "rb")
        except OSError:
            return self._json({"hata": "Dosya bulunamadı"}, 404)
        bas, son, kod = 0, boyut - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                bas = int(m.group(1))
                if m.group(2):
                    son = min(int(m.group(2)), boyut - 1)
            else:
                bas = max(0, boyut - int(m.group(2)))
            if bas > son or bas >= boyut:
                f.close()
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % boyut)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            kod = 206
        uzunluk = son - bas + 1
        self.send_response(kod)
        self.send_header("Content-Type", mimetypes.guess_type(yol)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(uzunluk))
        self.send_header("Accept-Ranges", "bytes")
        if kod == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (bas, son, boyut))
        tur = "inline" if izle else "attachment"
        self.send_header("Content-Disposition", "%s; filename=\"video.mp4\"; filename*=UTF-8''%s" % (tur, quote(ad)))
        self.end_headers()
        try:
            if self.command != "HEAD":
                f.seek(bas)
                kalan = uzunluk
                while kalan > 0:
                    parca = f.read(min(65536, kalan))
                    if not parca:
                        break
                    self.wfile.write(parca)
                    kalan -= len(parca)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            f.close()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        yol = u.path
        if yol == "/":
            try:
                sayfa = (UYGULAMA / "sayfa.html").read_bytes()
            except OSError:
                return self._gonder(500, "sayfa.html bulunamadı".encode("utf-8"), "text/plain; charset=utf-8")
            return self._gonder(200, sayfa, "text/html; charset=utf-8")
        if yol == "/favicon.ico":
            return self._gonder(204, b"", "image/x-icon")
        if yol == "/api/durum":
            with KILIT:
                d = dict(DURUM)
                d["liste"] = [{"id": k["id"], "baslik": k["baslik"], "bilgi": k["bilgi"], "kapak": bool(k["kapak"])}
                              for k in KAYITLAR]
            d["sirada"] = KUYRUK.qsize()
            d["hazir"] = HAZIR.is_set()
            if ANDROID and not IZIN["gerek"]:
                d["klasor"] = "Movies/TikTok (galeri)"
            else:
                d["klasor"] = str(KLASOR_SON["yol"] or klasor_bul())
            d["yerel"] = True
            d["kod"] = KOD_SURUMU
            d["izin_gerek"] = bool(IZIN["gerek"]) and ANDROID
            d["tani"] = list(TANI)
            return self._json(d)
        if yol.startswith("/kapak/"):
            k = kayit_bul(yol[7:])
            if k and k["kapak"]:
                try:
                    with open(k["kapak"], "rb") as f:
                        b = f.read()
                    return self._gonder(200, b, resim_turu(b), {"Cache-Control": "max-age=3600"})
                except OSError:
                    pass
            return self._json({"hata": "Yok"}, 404)
        if yol.startswith("/dosya/"):
            k = kayit_bul(yol[7:])
            if k:
                return self._dosya(k["yol"], os.path.basename(k["yol"]), q.get("izle", [""])[0] == "1")
            return self._json({"hata": "Yok"}, 404)
        self._json({"hata": "Bulunamadı"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20000:
                return self._json({"ok": False, "hata": "Çok büyük"}, 413)
            veri = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"ok": False, "hata": "Bozuk istek"}, 400)
        if u.path == "/api/indir":
            try:
                tur, parcalar = girdiyi_coz(str(veri.get("girdi", "")))
            except ValueError as e:
                return self._json({"ok": False, "hata": str(e)})
            KUYRUK.put((tur, parcalar))
            return self._json({"ok": True})
        if u.path == "/api/izin":
            ok = tum_dosya_izni_iste()
            if not ok:
                with KILIT:
                    DURUM["mesaj"] = "İzin ekranı açılamadı."
            return self._json({"ok": ok})
        if u.path == "/api/durdur":
            durdur()
            return self._json({"ok": True})
        if u.path == "/api/tasi":
            try:
                kayit_tasi(str(veri.get("id", "")), 1 if int(veri.get("yon", 0)) > 0 else -1)
            except (TypeError, ValueError):
                pass
            return self._json({"ok": True})
        self._json({"hata": "Bulunamadı"}, 404)


def main():
    try:
        sunucu = ThreadingHTTPServer(("127.0.0.1", PORT), Isleyici)
    except OSError:
        return
    sunucu.daemon_threads = True
    threading.Thread(target=hazirla, daemon=True).start()
    threading.Thread(target=isci, daemon=True).start()
    android_hazirla()   # Java sınıflarını ana iş parçacığında yükle
    if ANDROID:
        izin_iste()
    sunucu.serve_forever()


if __name__ == "__main__":
    main()
