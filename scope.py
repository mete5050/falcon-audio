"""SES GORSELLESTIRICI - Falcon temasi
Bilgisayarda calan sesi (Spotify vb.) WASAPI loopback ile yakalar.
- 6 panel; her panelin ustundeki menuden gorunum secilir
- Paneller arasindaki cizgileri surukleyerek boyut ayarlanir
- Ust cubukta FFT boyu, nota hizi, dusus hizi ayarlari
Gorunumler: Osiloskop, Spektrum, Kromagram, Nota x Oktav, Waterfall,
            Oktav Sarmali (animasyon), Oktav Enerjisi
"""
import threading
import numpy as np
import pyaudiowpatch as pyaudio
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets, QtGui

# ---------------- TEMA (falconrocketry.com) ----------------
# Her tema: zemin tonlari + vurgu (RED = ana vurgu adi tarihsel; tema rengini tasir)
THEMES = {
    "Falcon":        dict(INK="#050505", PANEL="#0d0d0f", PANEL2="#141417", LINE="#26262a", FG="#f4f4f5",
                          MUTED="#a1a1aa", RED="#e3202a", RED_BRIGHT="#ff3b42", RED_DEEP="#8f0f15"),
    "Analog Amber":  dict(INK="#070402", PANEL="#0f0a06", PANEL2="#1a120a", LINE="#2e2216", FG="#f6ead8",
                          MUTED="#b39b7d", RED="#ff6a13", RED_BRIGHT="#ff9a3c", RED_DEEP="#7a2a06"),
    "Neon Cyan":     dict(INK="#03060a", PANEL="#070d14", PANEL2="#0d1620", LINE="#1c2a38", FG="#e8f6ff",
                          MUTED="#8aa4b8", RED="#00c8ff", RED_BRIGHT="#5ce1ff", RED_DEEP="#004f6e"),
    "Fosfor Yesil":  dict(INK="#020603", PANEL="#060d07", PANEL2="#0b160c", LINE="#1a2c1c", FG="#e6ffe9",
                          MUTED="#8fb595", RED="#20e05a", RED_BRIGHT="#6cff95", RED_DEEP="#0b5a22"),
    "Synthwave":     dict(INK="#07030c", PANEL="#0e0716", PANEL2="#170d22", LINE="#2c1c3e", FG="#fbefff",
                          MUTED="#b29cc4", RED="#ff2bd6", RED_BRIGHT="#ff7be6", RED_DEEP="#6a0f5a"),
    # bakalit / ceviz govde, krem yazi, sicak lamba amberi
    "Retro Analog":  dict(INK="#140d07", PANEL="#21170e", PANEL2="#2e2116", LINE="#5a4329", FG="#f2e4c4",
                          MUTED="#b9a37c", RED="#ff9d2e", RED_BRIGHT="#ffc966", RED_DEEP="#6e3a10",
                          FONT="Georgia"),
}
THEME = "Falcon"
globals().update(THEMES[THEME])

def rgb(h):
    c = QtGui.QColor(h); return (c.red(), c.green(), c.blue())
def mix(a, b, f):
    a, b = rgb(a), rgb(b)
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))
FONT = "Chakra Petch"
BASE_FONT = FONT
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
OCT_LO, OCT_HI = 1, 7
MIDI_LO, MIDI_HI = 12 * (OCT_LO + 1), 12 * (OCT_HI + 2) - 1   # C1..B7

# kenar yumusatma sadece sarmal animasyonda acik (her yerde acik olmasi FPS'i yer)
pg.setConfigOptions(antialias=False, background=PANEL, foreground=MUTED)

def theme_lut():
    pos = [0.0, 0.35, 0.7, 0.9, 1.0]
    cols = [rgb(INK), mix(INK, RED_DEEP, 0.7), rgb(RED), rgb(RED_BRIGHT), (255, 255, 255)]
    return pg.ColorMap(pos, cols).getLookupTable(nPts=256)

def apply_theme(name):
    """Global renkleri + LUT + pyqtgraph varsayilanlarini degistir (gorunumler sonra yeniden kurulur)."""
    global THEME, LUT
    THEME = name
    globals()["FONT"] = BASE_FONT                 # temanin kendi fontu yoksa varsayilan
    globals().update(THEMES[name])
    LUT = theme_lut()
    pg.setConfigOptions(background=PANEL, foreground=MUTED)

def red_lut():
    pos = [0.0, 0.35, 0.7, 0.9, 1.0]
    return theme_lut()
LUT = red_lut()

def style_plot(pl, title=None):
    pl.showGrid(x=True, y=True, alpha=0.12)
    for ax in ("left", "bottom"):
        a = pl.getAxis(ax)
        a.setPen(pg.mkPen(LINE)); a.setTextPen(pg.mkPen(MUTED))
        a.setStyle(tickFont=QtGui.QFont(FONT, 8))
    pl.setMenuEnabled(False)

# ---------------- SES YAKALAMA ----------------
p = pyaudio.PyAudio()
RATE, CH = 48000, 2
stream = None

def list_devices():
    """WASAPI loopback (calan ses) + mikrofon/hat girisleri. Varsayilan cikisin loopback'i once."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    devs = []
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d["hostApi"] != wasapi["index"] or d["maxInputChannels"] < 1:
            continue
        lb = d.get("isLoopbackDevice", False)
        label = ("🔊 Calan ses: " if lb else "🎤 Giris: ") + d["name"].replace(" [Loopback]", "")
        label += f"  ({int(d['defaultSampleRate'])} Hz)"
        default = lb and out["name"] in d["name"]
        devs.append((0 if default else (1 if lb else 2), label + ("  ★ varsayilan" if default else ""), d))
    devs.sort(key=lambda x: x[0])
    return [(l, d) for _, l, d in devs]

def open_stream(dev):
    global stream, RATE, CH, widx, filled, total
    if stream is not None:
        stream.stop_stream(); stream.close()
    RATE = int(dev["defaultSampleRate"])
    CH = max(1, min(2, dev["maxInputChannels"]))
    with lock:
        ring[:] = 0; widx = 0; filled = 0; total = 0
    tracker.reset()
    stream = p.open(format=pyaudio.paFloat32, channels=CH, rate=RATE, input=True,
                    input_device_index=dev["index"], frames_per_buffer=256,
                    stream_callback=cb)
    print(f"Yakalanan cihaz: {dev['name']}  {RATE} Hz, {CH} kanal")

RING = 65536
ring = np.zeros((RING, 2), dtype=np.float32)
widx = 0
filled = 0
total = 0            # yakalanan toplam ornek (mutlak ses zamani = total / RATE)
lock = threading.Lock()

def cb(data, frames, t, status):
    global widx, filled, total
    a = np.frombuffer(data, dtype=np.float32).reshape(-1, CH)
    if CH == 1:
        a = np.repeat(a, 2, axis=1)
    n = len(a)
    with lock:
        e = widx + n
        if e <= RING:
            ring[widx:e] = a
        else:
            k = RING - widx
            ring[widx:] = a[:k]; ring[:n - k] = a[k:]
        widx = e % RING
        filled = min(RING, filled + n)
        total += n
    return (None, pyaudio.paContinue)

def read_abs(start, n):
    """Mutlak ornek indeksinden n ornek oku (mono). Veri halkadan dustuyse None."""
    with lock:
        if start + n > total or start < total - filled:
            return None
        i = start % RING
        if i + n <= RING:
            a = ring[i:i + n]
        else:
            a = np.concatenate([ring[i:], ring[:i + n - RING]])
        return (a[:, 0] + a[:, 1]) * 0.5

class BeatTracker:
    """Arka plan is parcaciginda, GUI'den bagimsiz ~11 ms adimla calisir.
    - 3 bant (kick/snare/hat) icin log-enerji akisi (onset) zarfi
    - Vuruslar ses zamaniyla damgalanir (ekran FPS'i zamanlamayi bozmaz)
    - Tempo: son 6 sn zarfin otokorelasyonu (70-180 BPM, 120 civari hafif tercih)
    - Faz: bulunan periyotta zarfi en iyi hizalayan vurus konumu (kick agirlikli)"""
    BANDS = [(40, 150), (180, 1200), (6000, 16000), (1500, 5000)]   # KICK, SNARE govde, HAT, (snare hisirti)
    W = [1.0, 0.6, 0.25]
    def __init__(self):
        self.lk = threading.Lock()
        self.reset()
        threading.Thread(target=self.loop, daemon=True).start()
    def reset(self):
        with getattr(self, "lk", threading.Lock()):
            self.rate = None
            self.pos = None
            self.hits = []            # (zaman_s, bant)
            self.hits_s = []          # (zaman_s, bant, guc 0..1) - Davul Izi icin
            self.env = []             # birlesik onset zarfi
            self.prev = None
            self.hist = [[], [], [], []]
            self.last_hit = [0.0, 0.0, 0.0, 0.0]
            self.bpm = None; self.beat0 = None; self.last_tempo = 0.0
    def setup(self):
        self.rate = RATE
        self.N = 1024; self.H = 512
        self.win = np.hanning(self.N).astype(np.float32)
        f = np.fft.rfftfreq(self.N, 1 / self.rate)
        self.masks = [(f >= lo) & (f < hi) for lo, hi in self.BANDS]
        self.fps = self.rate / self.H
        self.pos = max(0, total - self.N)
    def loop(self):
        import time
        while True:
            try:
                self.step()
            except Exception as e:
                print("beat hata:", e)
            time.sleep(0.004)
    def step(self):
        if total < 4096:
            return
        if self.rate != RATE or self.pos is None:
            self.setup()
        while self.pos + self.N <= total:
            x = read_abs(self.pos, self.N)
            if x is None:                                  # geride kaldik: atla
                self.pos = total - self.N; continue
            t = (self.pos + self.N / 2) / self.rate
            mag = np.abs(np.fft.rfft(x * self.win)) ** 2
            db = np.array([10 * np.log10(mag[m].sum() + 1e-10) for m in self.masks])
            if self.prev is None:
                self.prev = db
            dE = np.maximum(10 ** (db / 10) - 10 ** (self.prev / 10), 0)   # dogrusal enerji artisi
            flux = np.maximum(db - self.prev, 0); self.prev = db
            with self.lk:
                thr = []
                for i in range(4):
                    h = self.hist[i]; h.append(flux[i]); del h[:-90]
                    thr.append(np.mean(h) + 1.6 * np.std(h) + 1.0)
                for i in range(3):
                    gap = 0.10 if i == 0 else 0.07
                    # snare = govde artisi VE ayni anda 1.5-5 kHz hisirti
                    # (kick'te hisirti yok, hi-hat'te govde yok)
                    # + hisirti artisi hi-hat bandina gore buyuk olmali (hi-hat enerjisi 6k ustunde)
                    if i == 1 and (flux[3] < 0.6 * thr[3] or dE[3] < 0.15 * dE[2]):
                        continue
                    if flux[i] > thr[i] and db[i] > -55 and t - self.last_hit[i] > gap:
                        self.last_hit[i] = t; self.hits.append((t, i))
                        self.hits_s.append((t, i, float(min(1.0, flux[i] / (2.5 * thr[i])))))
                self.hits = [hv for hv in self.hits if t - hv[0] < 10]
                self.hits_s = [hv for hv in self.hits_s if t - hv[0] < 10]
                self.env.append(float(np.dot(self.W, flux[:3])))
                del self.env[:-int(8 * self.fps)]
            self.pos += self.H
            if t - self.last_tempo > 1.0 and len(self.env) > 4 * self.fps:
                self.last_tempo = t; self.tempo(t)
    def tempo(self, now):
        e = np.array(self.env[-int(6 * self.fps):]); e = e - e.mean()
        if e.std() < 1e-6:
            return
        ac = np.correlate(e, e, "full")[len(e) - 1:]
        lags = np.arange(len(ac))
        bpm_l = 60 * self.fps / np.maximum(lags, 1)
        ok = (bpm_l >= 70) & (bpm_l <= 180)
        w = np.exp(-0.5 * (np.log2(bpm_l / 120) / 0.6) ** 2)   # 120 BPM civari tercih
        sc = np.where(ok, ac * w, -np.inf)
        L = int(np.argmax(sc))
        if L < 2 or not np.isfinite(sc[L]):
            return
        # parabolik ince ayar
        a_, b_, c_ = ac[L - 1], ac[L], ac[L + 1] if L + 1 < len(ac) else ac[L]
        Lf = L + 0.5 * (a_ - c_) / (a_ - 2 * b_ + c_ + 1e-12)
        bpm = 60 * self.fps / Lf
        # faz: periyot boyunca hangi kayma zarfla en iyi ortusur
        P = Lf; n = len(e)
        best, bph = -1, 0
        for ph in range(int(P)):
            idx = (n - 1 - ph - np.arange(0, n / P - 1) * P).astype(int)
            s = e[idx[idx >= 0]].sum()
            if s > best:
                best, bph = s, ph
        last_beat = now - bph / self.fps
        with self.lk:
            if self.bpm is not None and abs(bpm - self.bpm) < 2:
                bpm = 0.8 * self.bpm + 0.2 * bpm             # kucuk farklarda yumusat
            self.bpm = bpm; self.beat0 = last_beat
    def strengths(self, t0):
        with self.lk:
            return [h for h in self.hits_s if h[0] > t0]
    def snapshot(self):
        with self.lk:
            return self.bpm, self.beat0, list(self.hits)

tracker = BeatTracker()

class KbdRGB:
    """ASUS TUF tek bolgeli klavye RGB (G-Helper ile ayni yol: \\.\ATKACPI, DEVS 0x00100056).
    Renk kaydedilmez (0xB3); Armoury Crate / yeniden baslatma eski rengi geri getirir.
    Desteklenmeyen bilgisayarda sessizce devre disi kalir."""
    DEVS, IOCTL = 0x53564544, 0x0022240C
    def __init__(self):
        self.h = None; self.dev = None; self.last = None; self.ok = None
    def open(self):
        if self.ok is not None:
            return self.ok
        try:
            import ctypes, struct
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateFileW.restype = wintypes.HANDLE
            k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                          wintypes.LPVOID]
            h = k.CreateFileW(r"\\.\ATKACPI", 0xC0000000, 3, None, 3, 0x80, None)
            if h in (None, wintypes.HANDLE(-1).value):
                raise OSError("ATKACPI yok")
            self.k, self.h, self.ct, self.st, self.wt = k, h, ctypes, struct, wintypes
            for dev in (0x00100056, 0x0010005A):
                self.dev = dev
                if self._send(0, 0, 0, force=True):
                    break
            else:
                raise OSError("TUF RGB komutu kabul edilmedi")
            self.ok = True
        except Exception as e:
            print("Klavye RGB kullanilamiyor:", e); self.ok = False
        return self.ok
    def _send(self, r, g, b, force=False):
        c = (int(r), int(g), int(b))
        if c == self.last and not force:
            return True
        ct, st = self.ct, self.st
        args = st.pack("<I", self.dev) + bytes([0xB3, 0, c[0], c[1], c[2], 0xEB])
        buf = st.pack("<II", self.DEVS, len(args)) + args
        inb = ct.create_string_buffer(buf, len(buf)); outb = ct.create_string_buffer(16)
        n = self.wt.DWORD()
        ok = self.k.DeviceIoControl(self.h, self.IOCTL, inb, len(buf), outb, 16, ct.byref(n), None)
        res = st.unpack("<i", outb.raw[:4])[0]
        if ok and res == 1:
            self.last = c
        return bool(ok and res == 1)
    def set(self, rgb_):
        if self.open():
            self._send(*[max(0, min(255, v)) for v in rgb_])

kbd = KbdRGB()

class PitchTracker:
    """Arka planda 10 ms adimla perde (f0) takibi - vibrato icin.
    1) Kaba: yari-ton izgarasinda harmonik toplam (5 harmonik, log-genlik) -> oktav hatasi az
    2) Ince: kaba notanin +-60 cent'inde 2 cent adimla harmonik toplam (sifir dolgulu FFT,
       dogrusal ara degerleme) -> tek bin'den cok daha hassas
    Sonuc: (zaman, midi_kesirli, guven) listesi."""
    N, PAD = 2048, 16384
    LO, HI = 48, 102                 # C3..F#7: melodi araligi (bas hatti C2-B2 disarida)
    HW = np.array([1.0, 0.8, 0.6, 0.5, 0.4])
    def __init__(self, lo=48, hi=102):
        self.lk = threading.Lock(); self.rate = None; self.pos = None
        self.track = []; self.alive = True
        self.LO, self.HI = lo, hi
        threading.Thread(target=self.loop, daemon=True).start()
    def setup(self):
        self.rate = RATE; self.H = int(RATE / 100)
        self.win = np.hanning(self.N).astype(np.float32)
        self.df = RATE / self.PAD
        cm = np.arange(self.LO, self.HI + 1)
        self.cf = 440 * 2 ** ((cm - 69) / 12)
        self.pos = max(0, total - self.N)
        self.prev_k = None
        with self.lk:
            self.track = []
    def set_range(self, lo, hi):
        """Arama araligini degistir (midi). Takipci bir sonraki adimda yeniden kurulur."""
        self.LO, self.HI = lo, hi
        self.rate = None
    def loop(self):
        import time
        while self.alive:
            try:
                self.step()
            except Exception as e:
                print("pitch hata:", e)
            time.sleep(0.003)
    def hsum(self, ldb, f0):
        """f0 dizisi icin harmonik toplam skoru (dogrusal ara degerleme)."""
        h = np.arange(1, 6)[:, None] * f0[None, :]
        ax = np.arange(len(ldb))
        v = np.interp(h / self.df, ax, ldb, right=0)
        # harmonikler ARASI enerji cezasi: gercek notanin yarisi (alt oktav) adayi
        # tam bu ara noktalarda tepe bulur -> skoru duser, alt-oktav hatasi kesilir
        vi = np.interp((h[:4] + 0.5 * f0[None, :]) / self.df, ax, ldb, right=0)
        # ayni mantik 1/3 alt-harmonik icin (oktav + besli asagi hatasi)
        v3 = (np.interp((h[:3] + f0[None, :] / 3) / self.df, ax, ldb, right=0) +
              np.interp((h[:3] + 2 * f0[None, :] / 3) / self.df, ax, ldb, right=0))
        return ((self.HW[:, None] * v).sum(0) - 0.5 * (self.HW[:4, None] * vi).sum(0)
                - 0.3 * (self.HW[:3, None] * v3).sum(0))
    def step(self):
        if total < self.N * 2:
            return
        if self.rate != RATE or self.pos is None:
            self.setup()
        if total - self.pos > RATE:                        # cok geride: atla
            self.pos = total - self.N
        while self.pos + self.N <= total:
            x = read_abs(self.pos, self.N)
            t = (self.pos + self.N / 2) / self.rate
            self.pos += self.H
            if x is None:
                continue
            mag = np.abs(np.fft.rfft(x * self.win, n=self.PAD))
            db = 20 * np.log10(mag + 1e-9)
            top = db.max()
            if top < 20 * np.log10(self.N / 4) - 60:      # sessiz
                continue
            ldb = np.clip(db - (top - 45), 0, None)        # en guclu tepeden 45 dB'e kadar
            s = self.hsum(ldb, self.cf)
            k = int(np.argmax(s))
            # oktav kontrolu: bir oktav ustu neredeyse ayni gucteyse ustu sec
            # (alttaki aday baska seslerin harmoniklerinden puan topluyor olabilir)
            # sureklilik: onceki notadan uzak (oktav vb.) bir sicrama, onceki notanin
            # yakinindaki aday neredeyse ayni gucteyse reddedilir (oktav hatalarini keser)
            pk_ = getattr(self, "prev_k", None)
            if pk_ is not None and abs(k - pk_) >= 5:
                lo_, hi_ = max(0, pk_ - 1), min(len(s), pk_ + 2)
                k2 = lo_ + int(np.argmax(s[lo_:hi_]))
                if s[k2] > 0.85 * s[k]:
                    k = k2
            # oktav kontrolu SUReklilikten SONRA: yanlis (alt) oktava kilitlenmeyi kirar
            if k + 12 < len(s) and s[k + 12] > 0.8 * s[k]:
                k += 12
            self.prev_k = k
            conf = (s[k] - np.median(s)) / (s[k] + 1e-9)
            m0 = self.LO + k
            fine = m0 + np.arange(-0.6, 0.6001, 0.02)
            sf = self.hsum(ldb, 440 * 2 ** ((fine - 69) / 12))
            j = int(np.argmax(sf))
            if 0 < j < len(sf) - 1:                        # parabolik: < 2 cent
                a_, b_, c_ = sf[j - 1], sf[j], sf[j + 1]
                den = a_ - 2 * b_ + c_
                off = float(np.clip(0.5 * (a_ - c_) / den, -0.5, 0.5)) if den < -1e-9 else 0.0
            else:
                off = 0.0
            with self.lk:
                self.track.append((t, fine[j] + off * 0.02, conf,
                                   float(np.clip(sf[j] / (45 * 3.3), 0, 1))))   # guc 0..1
                del self.track[:-1500]
    def since(self, t0):
        with self.lk:
            return [p for p in self.track if p[0] > t0]

MEL_RANGES = [("Otomatik C3-F#7", 48, 102), ("Bas C2-B3", 36, 59),
              ("Erkek vokal C3-B4", 48, 71), ("Kadin vokal C4-B5", 60, 83),
              ("Yuksek C5-B6", 72, 95), ("Oktav 2", 36, 47), ("Oktav 3", 48, 59),
              ("Oktav 4", 60, 71), ("Oktav 5", 72, 83), ("Oktav 6", 84, 95)]

def now_audio():
    return total / RATE

def last(n):
    with lock:
        if filled < n:
            return None
        i = widx
        if i >= n:
            return ring[i - n:i].copy()
        return np.concatenate([ring[RING - (n - i):], ring[:i]])

# ---------------- ANALIZ ----------------
class Analyzer:
    """Iki cozunurluklu FFT: buyuk pencere (spektrum/bas) + kisa pencere (hizli nota)."""
    def __init__(self):
        self.decay = 0.80
        self.configure(8192, 2048)

    def configure(self, big, fast):
        self.BIG, self.FAST = big, fast
        self.PAD = max(8192, fast * 4)                 # kisa pencereyi sifirla doldur -> ince tepe
        self.win_big = np.hanning(big).astype(np.float32)
        self.win_fast = np.hanning(fast).astype(np.float32)
        self.f_big = np.fft.rfftfreq(big, 1 / RATE)[1:]
        self.f_fast = np.fft.rfftfreq(self.PAD, 1 / RATE)[1:]
        self.smooth_db = np.full(len(self.f_big), -110.0)
        # bin -> midi haritasi
        def mm(f):
            return np.clip(np.round(69 + 12 * np.log2(f / 440)), 0, 127).astype(int)
        self.mid_big, self.mid_fast = mm(self.f_big), mm(self.f_fast)
        # her nota icin hangi FFT? kisa pencerenin yari-ton ayirabildigi yerde kisa
        notes = np.arange(128)
        nf = 440 * 2 ** ((notes - 69) / 12)
        semiw = nf * (2 ** (1 / 12) - 1)
        self.use_fast = semiw > 1.6 * RATE / fast
        self.valid = semiw > 0.9 * RATE / big            # buyuk pencere de ayiramiyorsa gecersiz
        self.semi = np.zeros(128)
        self.semi_prev = np.zeros(128)
        # global kick dedektoru (arka plan flasi icin; panellerden bagimsiz)
        self.kick_mask = (self.f_fast >= 40) & (self.f_fast < 150)
        self.k_prev, self.k_hist, self.k_last = 0.0, [], 0.0
        self.k_clk = QtCore.QElapsedTimer(); self.k_clk.start()
        self.bass_flash = 0.0
        self.chroma = np.zeros(12)
        self.ready = False

    def run(self):
        a = last(max(self.BIG, self.FAST))
        if a is None:
            return None
        L, R = a[:, 0], a[:, 1]
        m = (L + R) * 0.5
        # buyuk FFT
        mb = np.abs(np.fft.rfft(m[-self.BIG:] * self.win_big))[1:] / (self.BIG / 4)
        db_big = 20 * np.log10(mb + 1e-9)
        self.smooth_db = np.maximum(db_big, self.smooth_db - 2.5)
        # kisa FFT (dusuk gecikme)
        mf = np.abs(np.fft.rfft(m[-self.FAST:] * self.win_fast, n=self.PAD))[1:] / (self.FAST / 4)
        db_fast = 20 * np.log10(mf + 1e-9)
        # yari-ton enerjileri (cok cozunurluklu)
        eb = np.bincount(self.mid_big, weights=mb ** 2, minlength=128)[:128]
        ef = np.bincount(self.mid_fast, weights=mf ** 2, minlength=128)[:128] * (self.FAST / self.PAD)
        e = np.where(self.use_fast, ef, eb) * self.valid
        e[:MIDI_LO] = 0; e[MIDI_HI + 1:] = 0
        mx = e.max()
        if mx > 1e-9:
            nd = np.clip((10 * np.log10(e / mx + 1e-12) + 40) / 40, 0, 1)
            if 10 * np.log10(mx) < -75:
                nd *= 0
        else:
            nd = np.zeros(128)
        self.semi_prev = self.semi.copy()
        self.semi = np.maximum(nd, self.semi * self.decay)   # aninda yukselir, ayarli duser
        # kromagram (60 Hz - 5 kHz, kisa FFT)
        sel = (np.arange(128) >= 35) & (np.arange(128) <= 111)
        c = np.bincount(np.arange(128)[sel] % 12, weights=e[sel], minlength=12)
        if c.max() > 1e-9:
            c = np.sqrt(c / c.max())
            self.chroma = np.maximum(c, self.chroma * self.decay)
        else:
            self.chroma *= self.decay
        # tepeler (kisa FFT, sifir dolgulu -> hassas)
        d = np.where((self.f_fast > 40) & (self.f_fast < 5000), db_fast, -200)
        pk = np.where((d[1:-1] > d[:-2]) & (d[1:-1] > d[2:]) & (d[1:-1] > d.max() - 30)
                      & (d[1:-1] > -70))[0] + 1
        pk = pk[np.argsort(d[pk])[::-1]]
        peaks = []
        for k in pk:
            a_, b_, c_ = db_fast[k - 1], db_fast[k], db_fast[k + 1]
            den = a_ - 2 * b_ + c_
            # aralik kenarinda (40 Hz / 5 kHz) tepe gercek tepe olmayabilir -> payda <= 0 degil;
            # o zaman ara degerleme sacmalar (NaN / negatif frekans). Kenetle.
            off = float(np.clip(0.5 * (a_ - c_) / den, -0.5, 0.5)) if den < -1e-9 else 0.0
            f = self.f_fast[k] + off * (RATE / self.PAD)
            if not np.isfinite(f) or f <= 0:
                continue
            if any(abs(np.log2(f / q[0])) < 0.04 for q in peaks):
                continue
            midi = 69 + 12 * np.log2(f / 440)
            n = int(round(midi))
            peaks.append((f, b_, NOTES[n % 12] + str(n // 12 - 1), int(round((midi - n) * 100))))
            if len(peaks) >= 6:
                break
        # kick: bas bandinda ani log-enerji artisi > uyarlanir esik
        kdb = 10 * np.log10(np.sum(mf[self.kick_mask] ** 2) + 1e-12)
        flux = max(kdb - self.k_prev, 0); self.k_prev = kdb
        h = self.k_hist; h.append(flux); del h[:-60]
        now = self.k_clk.elapsed() / 1000
        kick = (flux > np.mean(h) + 1.8 * np.std(h) + 1.5 and kdb > -45
                and now - self.k_last > 0.1)
        if kick:
            self.k_last = now
            self.bass_flash = 1.0
        else:
            self.bass_flash *= 0.82
        self.ready = True
        return dict(kick=kick, bass_flash=self.bass_flash,L=L, R=R, f_big=self.f_big, db_big=db_big, smooth=self.smooth_db,
                    mf=mf, f_fast=self.f_fast, fast_n=self.FAST,
                    semi=self.semi, onset=self.semi - self.semi_prev,
                    chroma=self.chroma, peaks=peaks)

TEMPL = []
for r in range(12):
    for q, iv in (("", (0, 4, 7)), ("m", (0, 3, 7)), ("7", (0, 4, 7, 10)), ("m7", (0, 3, 7, 10))):
        v = np.zeros(12); v[[(r + i) % 12 for i in iv]] = 1
        TEMPL.append((NOTES[r] + q, v / np.linalg.norm(v)))

def guess_chord(ch):
    if ch.max() < 0.2:
        return None, 0
    cn = ch / (np.linalg.norm(ch) + 1e-9)
    return max(((n, float(cn @ v)) for n, v in TEMPL), key=lambda x: x[1])

# ---------------- GORUNUMLER ----------------
HZ_MAJOR = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
HZ_MINOR = [30, 40, 60, 70, 80, 90, 150, 300, 400, 600, 700, 800, 900, 1500,
            3000, 4000, 6000, 7000, 8000, 9000, 15000]
def hz(f):
    return f"{f // 1000}k" if f >= 1000 else str(f)
def set_hz_ticks(axis):
    """Log eksende okunakli Hz etiketleri (0.002 kHz gibi SI karmasasi yerine)."""
    axis.enableAutoSIPrefix(False)
    axis.setTicks([[(np.log10(f), hz(f)) for f in HZ_MAJOR],
                   [(np.log10(f), "") for f in HZ_MINOR]])

WF_SEC_MAX = 30          # waterfall gecmisi (s)
WF_RATE = 40             # saniyede satir

class View:
    name = "?"
    extra = None            # panel basligina eklenecek ayar widget'i (opsiyonel)
    def dispose(self): pass
    def __init__(self):
        self.widget = pg.PlotWidget()
        self.pl = self.widget.getPlotItem()
        self.pl.hideButtons()                       # sol alttaki 'A' (oto-olcek) dugmesi
        style_plot(self.pl)
    def update(self, A): pass
    def reset(self): pass

class ScopeView(View):
    name = "Osiloskop"
    def __init__(self):
        super().__init__()
        self.pl.setYRange(-1, 1); self.pl.setLabel("bottom", "ms")
        self.cl = self.pl.plot(pen=pg.mkPen(RED_BRIGHT, width=1))
        self.cr = self.pl.plot(pen=pg.mkPen((244, 244, 245, 140), width=1))
        self.N = 1024
        self.t = np.arange(self.N) / RATE * 1000
    def update(self, A):
        L, R = A["L"], A["R"]
        seg = L[-4096:-self.N]
        idx = np.where((seg[:-1] < 0) & (seg[1:] >= 0))[0]
        s = len(L) - 4096 + (idx[-1] if len(idx) else 0)
        self.cl.setData(self.t, L[s:s + self.N]); self.cr.setData(self.t, R[s:s + self.N])

class SpectrumView(View):
    name = "Spektrum"
    def __init__(self):
        super().__init__()
        self.pl.setLogMode(x=True, y=False); self.pl.setYRange(-100, 5)
        self.pl.setXRange(np.log10(20), np.log10(20000), padding=0)
        set_hz_ticks(self.pl.getAxis("bottom"))
        self.pl.setLabel("left", "dB")
        self.pl.getViewBox().setLimits(xMin=np.log10(15), xMax=np.log10(24000))
        self.c = self.pl.plot(pen=pg.mkPen(RED_BRIGHT, width=1), fillLevel=-110,
                              brush=pg.mkBrush(*mix(PANEL, RED_DEEP, 0.35)))   # opak dolgu: yari saydam dolgu cok yavas
        # PlotDataItem sembolleri her karede yeniden kurulur (yavas); sabit ScatterPlotItem kullan.
        # Log modunu ScatterPlotItem uygulamaz -> x'i elle log10 veriyoruz.
        self.pk = pg.ScatterPlotItem(symbol="t", size=11, brush=pg.mkBrush(FG), pen=None)
        self.pl.addItem(self.pk)
        self.lbls = []
        for _ in range(6):
            t = pg.TextItem(color=FG, anchor=(0.5, 1)); t.setFont(QtGui.QFont(FONT, 8))
            t.hide(); self.pl.addItem(t); self.lbls.append(t)
        self.main = pg.TextItem(color=RED_BRIGHT, anchor=(1, 0))      # sag ust: tepelerle cakismaz
        self.main.setFont(QtGui.QFont(FONT, 15, QtGui.QFont.Bold))
        self.pl.addItem(self.main); self.main.setPos(np.log10(19000), 5)
    LOGF = np.logspace(np.log10(20), np.log10(20000), 900)
    def update(self, A):
        # binlerce FFT noktasi yerine log eksende 900 nokta (gorunur fark yok, cizim cok hizli)
        self.c.setData(self.LOGF, np.interp(self.LOGF, A["f_big"], A["smooth"]))
        pk = A["peaks"]
        # isaretler + yazilar ~15 Hz'de guncellenir: okunur kalir, her karede yeniden kurulmaz
        self.n = getattr(self, "n", 0) + 1
        if self.n % 4:
            return
        self.pk.setData([np.log10(q[0]) for q in pk], [q[1] for q in pk])
        # etiket cakismasini onle: gucluden zayifa, yakin (log-x'te) bir etiket varsa yazma
        shown = []
        for f, d, n, c in pk:
            lx = np.log10(f)
            if all(abs(lx - s) > 0.17 for s in shown):
                shown.append(lx)
                l = self.lbls[len(shown) - 1]
                l.setText(f"{n}\n{f:.0f}Hz {c:+d}c"); l.setPos(lx, d + 3); l.show()
        for l in self.lbls[len(shown):]:
            l.hide()
        self.main.setText(f"{pk[0][2]}  {pk[0][0]:.1f} Hz  {pk[0][3]:+d}c" if pk else "—")

class ChromaView(View):
    name = "Kromagram"
    def __init__(self):
        super().__init__()
        self.pl.setYRange(0, 1.15); self.pl.setMouseEnabled(False, False)
        self.pl.getAxis("bottom").setTicks([list(enumerate(NOTES))])
        self.bars = pg.BarGraphItem(x=np.arange(12), height=np.zeros(12), width=0.78,
                                    brush=RED_DEEP, pen=None)
        self.pl.addItem(self.bars)
        self.txt = pg.TextItem(color=FG, anchor=(0.5, 0))
        self.txt.setFont(QtGui.QFont(FONT, 14, QtGui.QFont.Bold))
        self.pl.addItem(self.txt); self.txt.setPos(5.5, 1.15)
    def update(self, A):
        ch = A["chroma"]; top = int(np.argmax(ch))
        if not hasattr(self, "bq"):
            self.bq = [pg.mkBrush(*mix(RED_DEEP, RED, i / 31)) for i in range(32)]
            self.btop = pg.mkBrush(255, 255, 255)          # baskin nota: bembeyaz
        self.bars.setOpts(height=ch, brushes=[self.btop if i == top else self.bq[int(ch[i] * 31)]
                                              for i in range(12)])
        n, s = guess_chord(ch)
        self.txt.setText(f"AKOR ~ {n}  ({s:.2f})" if n else "")

class WideChromaView(View):
    """Genis kromagram: oktavlar yan yana tek uzun cubuk dizisi.
    Mod (panel basligindan): Tum oktavlar (C1-B7, 84 cubuk) ya da en cok kullanilan
    3/4 ardisik oktav (uzun vadeli enerjiye gore otomatik, histerezisli).
    Baskin nota beyaz, her oktavin en guclu notasi acik renk."""
    name = "Genis Kromagram"
    MODES = [("Tum oktavlar 1-7", None), ("Otomatik 3 oktav", 3), ("Otomatik 4 oktav", 4)]
    def __init__(self):
        super().__init__()
        self.pl.setYRange(0, 1.15); self.pl.setMouseEnabled(False, False)
        self.bars = pg.BarGraphItem(x=np.arange(1), height=np.zeros(1), width=0.8, brush=RED_DEEP, pen=None)
        self.pl.addItem(self.bars)
        self.seps = []
        self.title = pg.TextItem("", color=MUTED, anchor=(0, 0))
        self.title.setFont(QtGui.QFont(FONT, 10)); self.pl.addItem(self.title)
        self.title.setPos(-0.5, 1.15)
        self.lt = np.zeros(OCT_HI - OCT_LO + 1)          # uzun vadeli oktav enerjisi
        self.bq = [pg.mkBrush(*mix(RED_DEEP, RED, i / 31)) for i in range(32)]
        self.b_oct = pg.mkBrush(*mix(RED_BRIGHT, "#ffffff", 0.45))
        self.b_top = pg.mkBrush(255, 255, 255)
        self.extra = QtWidgets.QComboBox()
        self.extra.addItems([m[0] for m in self.MODES])
        self.extra.currentIndexChanged.connect(lambda i: self.set_mode(self.MODES[i][1]))
        self.set_mode(None)
    def set_mode(self, n_oct):
        self.auto = n_oct is not None
        self.N_OCT = n_oct or (OCT_HI - OCT_LO + 1)
        self.lo = 3 if self.auto else OCT_LO
        n = 12 * self.N_OCT
        self.x = np.arange(n)
        self.bars.setOpts(x=self.x, height=np.zeros(n), width=0.8 if n <= 48 else 0.72,
                          brushes=[self.bq[0]] * n)          # firca sayisi = cubuk sayisi
        self.pl.setXRange(-0.7, n - 0.3, padding=0)
        for s in self.seps:
            self.pl.removeItem(s)
        self.seps = [pg.InfiniteLine(pos=12 * k - 0.5, angle=90, pen=pg.mkPen(LINE, width=1))
                     for k in range(1, self.N_OCT)]
        for s in self.seps:
            self.pl.addItem(s)
        self.set_ticks()
    def set_ticks(self):
        t = []
        names = (0, 4, 7) if self.N_OCT <= 4 else (0,)   # cok oktavda sadece C yaz
        for k in range(self.N_OCT):
            for i, nm in enumerate(NOTES):
                if i in names:
                    t.append((12 * k + i, f"{nm}{self.lo + k}" if i == 0 else nm))
        self.pl.getAxis("bottom").setTicks([t])
        self.title.setText(f"OKTAV {self.lo}–{self.lo + self.N_OCT - 1}" + ("  (otomatik)" if self.auto else ""))
    def update(self, A):
        semi = A["semi"]
        g = semi[MIDI_LO:MIDI_HI + 1].reshape(-1, 12)
        if self.auto:
            self.lt = 0.995 * self.lt + 0.005 * g.sum(axis=1)  # ~3 sn'lik ortalama
            nO = len(self.lt)
            sums = [self.lt[i:i + self.N_OCT].sum() for i in range(nO - self.N_OCT + 1)]
            best = int(np.argmax(sums)) + OCT_LO
            cur = self.lo - OCT_LO
            if best != self.lo and sums[best - OCT_LO] > 1.25 * sums[cur] + 1e-6:
                self.lo = best; self.set_ticks()
        m0 = 12 * (self.lo + 1)
        h = semi[m0:m0 + 12 * self.N_OCT]
        top = int(np.argmax(h))
        octmax = h.reshape(-1, 12).max(axis=1)
        br = []
        for i, v in enumerate(h):
            if i == top and v > 0.3:
                br.append(self.b_top)
            elif v > 0.3 and v == octmax[i // 12]:
                br.append(self.b_oct)
            else:
                br.append(self.bq[int(v * 31)])
        self.bars.setOpts(height=h, brushes=br)

class MelodyView(View):
    """Melodi izi: PitchTracker'dan saniyede 100 olcum, cent hassasiyetinde surekli cizgi.
    Vibrato: son ~0.7 sn'lik kesintisiz bolumde perde salinimi -> hiz (Hz) ve derinlik (+-cent)."""
    name = "Melodi Izi"
    SPAN = 6.0                                 # gosterilen sure (s)
    LO, HI = 48, 102
    CONF = 0.2                                 # bu guvenin altindaki olcumler cizilmez
    def __init__(self):
        super().__init__()
        self.pl.setXRange(-self.SPAN, 0, padding=0); self.pl.setLabel("bottom", "saniye")
        self.pl.getViewBox().setMouseEnabled(x=False, y=True)
        self.pl.getViewBox().setLimits(yMin=self.LO - 2, yMax=self.HI + 2, minYRange=1)
        self.pl.setYRange(54, 70, padding=0)
        self.pl.getAxis("left").setTicks([[(m, f"{NOTES[m % 12]}{m // 12 - 1}")
                                           for m in range(self.LO, self.HI + 1) if "#" not in NOTES[m % 12]],
                                          [(m, "") for m in range(self.LO, self.HI + 1)]])
        self.pl.showGrid(x=True, y=True, alpha=0.12)
        self.line = self.pl.plot(pen=pg.mkPen(*rgb(RED), 110, width=1), connect="finite")
        self.dots = pg.ScatterPlotItem(pen=None, size=4)
        self.pl.addItem(self.dots)
        # genlige gore renk: koyu kirmizi -> parlak kirmizi -> beyaz (onbellekli)
        self.b = np.array([pg.mkBrush(*[int(c) for c in LUT[int(70 + 185 * i / 15)][:3]])
                           for i in range(16)], dtype=object)
        self.head = pg.ScatterPlotItem(pen=pg.mkPen(RED_BRIGHT, width=2), brush=pg.mkBrush(255, 255, 255), size=11)
        self.pl.addItem(self.head)
        self.lbl = pg.TextItem("", color=FG, anchor=(1, 0)); self.lbl.setFont(QtGui.QFont(FONT, 14, QtGui.QFont.Bold))
        self.vib = pg.TextItem("", color=RED_BRIGHT, anchor=(1, 0)); self.vib.setFont(QtGui.QFont(FONT, 11, QtGui.QFont.Bold))
        self.pl.addItem(self.lbl); self.pl.addItem(self.vib)
        self.n = 0
        if THEME == "Retro Analog":                # kayit seridi: kagit + murekkep kalem
            ink = (28, 38, 92)
            self.widget.setBackground("#efe4c8")
            for ax in ("left", "bottom"):
                a = self.pl.getAxis(ax); a.setPen(pg.mkPen("#8a6a44")); a.setTextPen(pg.mkPen("#4a3420"))
            self.pl.showGrid(x=True, y=True, alpha=0.35)
            self.line.setPen(pg.mkPen(*ink, 200, width=1.4))
            self.b = np.array([pg.mkBrush(*ink, int(70 + 185 * i / 15)) for i in range(16)], dtype=object)
            self.head.setPen(pg.mkPen("#7a1010", width=2)); self.head.setBrush(pg.mkBrush(*ink))
            self.lbl.setColor("#2a1c0e"); self.vib.setColor("#9a1a10")
        # bu panele ozel perde takipcisi + oktav secimi (paneller birbirinden bagimsiz)
        self.pt = PitchTracker(*MEL_RANGES[0][1:])
        self.extra = QtWidgets.QComboBox()
        self.extra.addItems([r[0] for r in MEL_RANGES])
        self.extra.setToolTip("Bu panelin perde aradigi aralik")
        self.extra.currentIndexChanged.connect(lambda i: self.pt.set_range(*MEL_RANGES[i][1:]))
    def dispose(self):
        self.pt.alive = False
    @staticmethod
    def clean(t, m, s):
        """Aykiri olcumleri at: 7'li kayan medyandan 1 yari tondan fazla sapan noktalar
        (kisa oktav/harmonik hatalari). Gercek nota gecisleri birkac olcum surdugu icin kalir."""
        if len(m) < 7:
            return t, m, s
        pad = np.pad(m, 3, mode="edge")
        med = np.median(np.lib.stride_tricks.sliding_window_view(pad, 7), axis=1)
        keep = np.abs(m - med) < 1.0
        return t[keep], m[keep], s[keep]
    @staticmethod
    def vibrato(t, m):
        """Son kesintisiz bolumden vibrato hizi/derinligi (3-9 Hz salinim)."""
        if len(t) < 60:
            return None
        seg_t, seg_m = t[-100:], m[-100:]                  # son ~1 sn
        if np.any(np.diff(seg_t) > 0.1) or np.ptp(seg_m) > 2.0:
            return None
        x = seg_m - np.polyval(np.polyfit(seg_t, seg_m, 2), seg_t)   # yavas egimi cikar
        x = np.convolve(x, np.ones(3) / 3, mode="same")              # olcum gurultusunu yumusat
        z = np.nonzero(np.diff(np.signbit(x[1:-1])))[0]              # sifir gecisleri
        if len(z) < 4:
            return None
        half = np.diff(seg_t[1:-1][z])                               # yarim periyotlar
        hp = np.median(half); rate = 1 / (2 * hp)
        regular = np.std(half) / hp < 0.35
        depth = (np.percentile(x, 95) - np.percentile(x, 5)) / 2 * 100
        if not (3 <= rate <= 9 and regular and depth >= 8):
            return None
        return rate, depth
    def update(self, A):
        now = (total - PitchTracker.N / 2) / RATE
        tr = self.pt.since(now - self.SPAN)
        if not tr:
            self.line.setData([], []); self.dots.setData([], []); self.head.hide(); return
        a = np.array(tr); t, m, c, s = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
        ok = c > self.CONF
        t, m, s = t[ok], m[ok], s[ok]
        if len(t) < 2:
            self.head.hide(); return
        t, m, s = self.clean(t, m, s)
        if len(t) < 2:
            self.head.hide(); return
        brk = np.nonzero((np.diff(t) > 0.06) | (np.abs(np.diff(m)) > 0.8))[0] + 1
        x = t - now
        xs = np.insert(x, brk, np.nan); ys = np.insert(m, brk, np.nan)
        self.line.setData(xs, ys)
        q = np.clip((s * 15 * 1.6).astype(int), 0, 15)
        self.dots.setData(x, m, brush=self.b[q])
        live = now - t[-1] < 0.06
        if live:
            self.head.setData([x[-1]], [m[-1]]); self.head.show()
        else:
            self.head.hide()
        self.n += 1
        if self.n % 4 == 0:                    # yazilar ~10 Hz
            if live:
                nn = int(round(m[-1]))
                self.lbl.setText(f"{NOTES[nn % 12]}{nn // 12 - 1}  {int(round((m[-1] - nn) * 100)):+d}c")
            v = self.vibrato(t, m) if live else None
            self.vib.setText(f"VIBRATO  {v[0]:.1f} Hz  ±{v[1]:.0f}c" if v else "")
            # gorunum takip: son 1.5 sn medyani etrafinda +-8 yari ton
            rec = m[t > now - 1.5]
            if len(rec) > 10:
                cc = float(np.median(rec))
                self.yc = cc if not hasattr(self, "yc") else 0.85 * self.yc + 0.15 * cc
                # secilen oktav araliginin disina kaymasin
                lo, hi = self.pt.LO - 1, self.pt.HI + 1
                yc = min(max(self.yc, lo + 8), hi - 8) if hi - lo > 16 else (lo + hi) / 2
                self.pl.setYRange(yc - 8, yc + 8, padding=0)
        yr = self.pl.getViewBox().viewRange()[1]
        self.lbl.setPos(-0.1, yr[1]); self.vib.setPos(-0.1, yr[1] - (yr[1] - yr[0]) * 0.12)

class DrumGridView(View):
    """Davul izgarasi: kick/snare/hi-hat vuruslari kick'ten bulunan BPM'e gore
    16 adimlik (1 olcu, 16'lik) izgaraya duser. Onceki olculer soluk kalir, boylece kalip olusur."""
    name = "Davul Izgarasi"
    BANDS = [("HI-HAT",), ("SNARE",), ("KICK",)]          # ekran sirasi (alttan uste)
    def __init__(self):
        super().__init__()
        self.pl.setMouseEnabled(False, False); self.pl.showGrid(False, False)
        self.pl.setRange(xRange=(-0.6, 15.6), yRange=(-0.6, 3.1), padding=0)
        self.pl.getAxis("bottom").setTicks([[(i, str(i // 4 + 1) if i % 4 == 0 else "") for i in range(16)]])
        self.pl.getAxis("left").setTicks([[(i, b[0]) for i, b in enumerate(self.BANDS)]])
        xs, ys = np.meshgrid(np.arange(16), np.arange(3)); self.xs, self.ys = xs.ravel(), ys.ravel()
        self.cells = pg.ScatterPlotItem(symbol="s", pxMode=False, size=0.82, pen=None)
        self.play = pg.LinearRegionItem(values=(-0.5, 0.5), movable=False,
                                        brush=pg.mkBrush(255, 255, 255, 25), pen=pg.mkPen(None))
        self.pl.addItem(self.play); self.pl.addItem(self.cells)
        self.info = pg.TextItem("", color=FG, anchor=(0.5, 0)); self.info.setFont(QtGui.QFont(FONT, 13, QtGui.QFont.Bold))
        self.pl.addItem(self.info); self.info.setPos(7.5, 3.1)
        self.grid = np.zeros((3, 16))
        self.bar = None; self.last_t = 0.0; self.down = 0; self.cur_step = -1; self.dirty = True
        self.b = np.array([pg.mkBrush(*[int(c) for c in LUT[int(20 + 235 * i / 15)][:3]]) for i in range(16)], dtype=object)
        self.b_beat = pg.mkBrush(26, 26, 30); self.b_off = pg.mkBrush(18, 18, 21)
        self.empty = [self.b_beat if x % 4 == 0 else self.b_off for x in self.xs]
        self.cells.setData(self.xs, self.ys, brush=self.empty)
    def update(self, A):
        # vurus algilama + tempo arka plandaki BeatTracker'da, ses zamaniyla (FPS'ten bagimsiz)
        bpm, beat0, hits = tracker.snapshot()
        if bpm is None:
            self.info.setText("Tempo araniyor…")
            return
        now = now_audio()
        beat = 60 / bpm
        # olcu basi: 4 vurus konumundan hangisinde kick yogun (histerezisli)
        cnt = np.zeros(4)
        for t, b in hits:
            if b == 0:
                k = (t - beat0) / beat; r = round(k)
                if abs(k - r) < 0.25:
                    cnt[int(r) % 4] += 1
        if cnt.max() > cnt[self.down] + 1:
            self.down = int(np.argmax(cnt))
        bar0 = beat0 + self.down * beat
        step = beat / 4
        # yeni vuruslari KENDI zaman damgalariyla yerlestir
        for t, b in hits:
            if t <= self.last_t:
                continue
            p = int(round((t - bar0) / step))
            if self.bar is not None and p // 16 >= self.bar:
                self.grid[2 - b, p % 16] = 1.0; self.dirty = True
        if hits:
            self.last_t = max(self.last_t, hits[-1][0])
        pos = (now - bar0) / step
        bar = int(pos // 16)
        if bar != self.bar:
            if self.bar is not None:
                self.grid *= 0.45                         # yeni olcu: eskiler soluklasir
            self.bar = bar; self.dirty = True
        s = int(pos) % 16
        if s != self.cur_step:
            self.cur_step = s; self.play.setRegion((s - 0.5, s + 0.5))
            self.info.setText(f"{bpm:.0f} BPM   olcu {bar % 1000 + 1}")
        if self.dirty:                                     # sadece degisince yeniden boya
            self.dirty = False
            g = self.grid.ravel()
            self.cells.setData(self.xs, self.ys,
                               brush=[self.b[int(v * 15)] if v > 0.05 else e for v, e in zip(g, self.empty)])

class NoteOctaveView(View):
    name = "Nota x Oktav"
    def __init__(self):
        super().__init__()
        self.pl.setMouseEnabled(False, False)
        self.img = pg.ImageItem(); self.img.setLookupTable(LUT)
        nO = OCT_HI - OCT_LO + 1
        self.img.setImage(np.zeros((12, nO)), autoLevels=False, levels=[0, 1])
        self.img.setRect(QtCore.QRectF(-0.5, OCT_LO - 0.5, 12, nO))
        self.pl.addItem(self.img)
        self.pl.getAxis("bottom").setTicks([list(enumerate(NOTES))])
        self.pl.getAxis("left").setTicks([[(o, str(o)) for o in range(OCT_LO, OCT_HI + 1)]])
        self.pl.setXRange(-0.5, 11.5, padding=0); self.pl.setYRange(OCT_LO - 0.5, OCT_HI + 0.5, padding=0)
        self.pl.showGrid(False, False)
        # tepe hucreleri: bembeyaz kare + parlama (ust ust: hale + kare)
        self.glow = pg.ScatterPlotItem(symbol="s", pxMode=False, pen=None,
                                       brush=pg.mkBrush(255, 255, 255, 70))
        self.hot = pg.ScatterPlotItem(symbol="s", pxMode=False, size=0.92, pen=None,
                                      brush=pg.mkBrush(255, 255, 255))
        self.pl.addItem(self.glow); self.pl.addItem(self.hot)
        self.top = pg.TextItem(color=INK, anchor=(0.5, 0.5))
        self.top.setFont(QtGui.QFont(FONT, 10, QtGui.QFont.Bold)); self.pl.addItem(self.top)
    def update(self, A):
        g = A["semi"][MIDI_LO:MIDI_HI + 1].reshape(-1, 12).T
        self.img.setImage(g, autoLevels=False, levels=[0, 1])
        # tepe = komsularindan (nota ve oktav yonunde) guclu ve > 0.75 olan hucreler
        pad = np.pad(g, 1)
        c = pad[1:-1, 1:-1]
        loc = ((c >= pad[:-2, 1:-1]) & (c >= pad[2:, 1:-1]) &
               (c >= pad[1:-1, :-2]) & (c >= pad[1:-1, 2:]) & (c > 0.75))
        ni, oi = np.nonzero(loc)
        if len(ni) > 8:
            k = np.argsort(c[ni, oi])[::-1][:8]; ni, oi = ni[k], oi[k]
        self.hot.setData(ni, oi + OCT_LO)
        self.glow.setData(ni, oi + OCT_LO, size=1.35)
        ni, oi = np.unravel_index(np.argmax(g), g.shape)
        if g[ni, oi] > 0.3:
            self.top.setText(f"{NOTES[ni]}{oi + OCT_LO}"); self.top.setPos(ni, oi + OCT_LO)
        else:
            self.top.setText("")

class WaterfallView(View):
    """Y ekseni = saniye (0 = simdi, ustte). Ust cubuktaki 'Waterfall' ayari veya
    fare tekerlegi (Y ekseni uzerinde) ile sure degisir. Sag tik = sifirla."""
    name = "Waterfall"
    BINS = 600
    seconds = 8
    def __init__(self):
        super().__init__()
        self.ROWS = WF_SEC_MAX * WF_RATE
        self.lf = np.linspace(np.log10(20), np.log10(20000), self.BINS)
        self.wf = np.full((self.BINS, self.ROWS), -110.0)
        self.img = pg.ImageItem(); self.img.setLookupTable(LUT)
        self.img.setImage(self.wf, autoLevels=False, levels=[-90, -10])
        self.img.setRect(QtCore.QRectF(self.lf[0], 0, self.lf[-1] - self.lf[0], WF_SEC_MAX))
        self.pl.addItem(self.img); self.pl.invertY(True)
        self.pl.showGrid(x=True, y=True, alpha=0.15)
        self.pl.setLabel("left", "saniye once")
        set_hz_ticks(self.pl.getAxis("bottom"))
        vb = self.pl.getViewBox()
        vb.setMouseEnabled(x=False, y=True)
        vb.setLimits(xMin=self.lf[0], xMax=self.lf[-1], yMin=0, yMax=WF_SEC_MAX,
                     minYRange=0.5)
        self.pl.setXRange(self.lf[0], self.lf[-1], padding=0)
        self.set_seconds(WaterfallView.seconds)
        self.acc = 0.0
        self.clk = QtCore.QElapsedTimer(); self.clk.start()
    def set_seconds(self, s):
        self.pl.setYRange(0, s, padding=0)
    def update(self, A):
        # zaman tabanli: FPS'ten bagimsiz olarak saniyede WF_RATE satir
        self.acc += self.clk.restart() / 1000 * WF_RATE
        n = int(self.acc)
        if n <= 0:
            return
        self.acc -= n; n = min(n, 10)
        row = np.interp(self.lf, np.log10(A["f_big"]), A["db_big"])
        self.wf[:, n:] = self.wf[:, :-n].copy(); self.wf[:, :n] = row[:, None]
        # sadece gorunen saniyeleri boya (30 sn'nin tamamini degil)
        ymax = self.pl.getViewBox().viewRange()[1][1]
        rows = int(np.clip(np.ceil(ymax * WF_RATE) + 2, 2, self.ROWS))
        self.img.setImage(self.wf[:, :rows], autoLevels=False, levels=[-90, -10])
        self.img.setRect(QtCore.QRectF(self.lf[0], 0, self.lf[-1] - self.lf[0], rows / WF_RATE))

class OctaveEnergyView(View):
    name = "Oktav Enerjisi"
    def __init__(self):
        super().__init__()
        n = OCT_HI - OCT_LO + 1
        self.x = np.arange(OCT_LO, OCT_HI + 1)
        self.pl.setYRange(0, 1.05); self.pl.setMouseEnabled(False, False)
        self.pl.getAxis("bottom").setTicks([[(o, f"Okt {o}") for o in self.x]])
        self.bars = pg.BarGraphItem(x=self.x, height=np.zeros(n), width=0.75, brush=RED, pen=None)
        self.peak = pg.ScatterPlotItem(symbol="s", size=10, brush=FG, pen=None)
        self.pl.addItem(self.bars); self.pl.addItem(self.peak)
        self.hold = np.zeros(n)
        self.cen = pg.TextItem(color=FG, anchor=(0, 0)); self.cen.setFont(QtGui.QFont(FONT, 11))
        self.pl.addItem(self.cen); self.cen.setPos(OCT_LO - 0.4, 1.05)
    def update(self, A):
        g = A["semi"][MIDI_LO:MIDI_HI + 1].reshape(-1, 12)
        e = g.mean(axis=1); e = e / (e.max() + 1e-9) * min(1, g.max() + 0.001)
        self.hold = np.maximum(e, self.hold - 0.01)
        self.bars.setOpts(height=e)
        self.peak.setData(self.x, self.hold)
        w = g.sum(axis=1)
        if w.sum() > 0.05:
            c = (w * self.x).sum() / w.sum()
            self.cen.setText(f"Agirlik merkezi: oktav {c:.2f}")

class SpiralView(View):
    """Oktav sarmali: aci = nota, yaricap = oktav. Aktif notalar parlar,
    yeni vuruslarda halkalar yayilir, sarmal muzikle doner."""
    name = "Oktav Sarmali"
    def __init__(self):
        super().__init__()
        self.pl.hideAxis("left"); self.pl.hideAxis("bottom"); self.pl.showGrid(False, False)
        self.pl.setAspectLocked(True); self.pl.setMouseEnabled(False, False)
        self.pl.setRange(xRange=(-5.8, 5.8), yRange=(-5.8, 5.8), padding=0)
        self.midis = np.arange(MIDI_LO, MIDI_HI + 1)
        self.rot = 0.0; self.spin = 0.0
        self.guide = self.pl.plot(pen=pg.mkPen((*rgb(RED), 45), width=1), antialias=True)
        self.links = self.pl.plot(pen=pg.mkPen((*rgb(RED_BRIGHT), 110), width=1.2), connect="pairs",
                                  antialias=True)
        self.halo = pg.ScatterPlotItem(pen=None, pxMode=True, antialias=False)
        self.dots = pg.ScatterPlotItem(pen=None, pxMode=True, antialias=True)
        self.rings = pg.ScatterPlotItem(brush=None, pxMode=True, antialias=True)
        self.parts = pg.ScatterPlotItem(pen=None, pxMode=True, size=3)
        for it in (self.halo, self.rings, self.parts, self.dots):
            self.pl.addItem(it)
        self.lbls = []
        for i, n in enumerate(NOTES):
            t = pg.TextItem(n, color=MUTED, anchor=(0.5, 0.5)); t.setFont(QtGui.QFont(FONT, 9))
            self.pl.addItem(t); self.lbls.append(t)
        self.center = pg.TextItem("", color=FG, anchor=(0.5, 0.5))
        self.center.setFont(QtGui.QFont(FONT, 20, QtGui.QFont.Bold)); self.pl.addItem(self.center)
        self.ring_list = []      # [x, y, yas]
        self.part = np.zeros((0, 5))   # x y vx vy omur
        # fircalar/kalemler onceden hazirlanir (her karede mkBrush cok yavas)
        Q = 64
        self.Q = Q
        self.b_dot = np.array([pg.mkBrush(*[int(c) for c in LUT[int(i / (Q - 1) * 255)][:3]], 230)
                               for i in range(Q)], dtype=object)
        self.b_halo = np.array([pg.mkBrush(*rgb(RED_BRIGHT), int(70 * i / (Q - 1))) for i in range(Q)],
                               dtype=object)
        self.b_part = np.array([pg.mkBrush(*mix(RED_BRIGHT, "#ffffff", 0.7), int(255 * i / (Q - 1))) for i in range(Q)],
                               dtype=object)
        self.p_ring = np.array([pg.mkPen(*rgb(RED_BRIGHT), int(255 * (1 - t / 30)), width=1.5)
                                for t in range(32)], dtype=object)
        self.fine = np.linspace(MIDI_LO, MIDI_HI, 300)
        self.lbl_r = 0.6 + (OCT_HI + 1 - OCT_LO) * 0.62 + 0.3
    def pos(self, midi):
        pc = midi % 12; o = midi / 12.0 - 1
        r = 0.6 + (o - OCT_LO) * 0.62
        ang = np.pi / 2 - pc * 2 * np.pi / 12 + self.rot
        return r * np.cos(ang), r * np.sin(ang)
    def update(self, A):
        semi = A["semi"][self.midis]; on = A["onset"][self.midis]
        energy = float(semi.mean())
        self.spin = 0.9 * self.spin + 0.1 * (0.002 + energy * 0.03)
        self.rot += self.spin
        x, y = self.pos(self.midis)
        gx, gy = self.pos(self.fine); self.guide.setData(gx, gy)
        # renk: koyu kirmizi -> parlak kirmizi -> beyaz (onbellekli fircalar)
        qi = (np.clip(semi, 0, 1) * (self.Q - 1)).astype(int)
        # boyutlar 12 sabit seviyeye yuvarlanir -> sembol atlasi onbellekten gelir
        lv = np.round(np.clip(semi, 0, 1) ** 2 * 11) / 11
        cq = (lv * (self.Q - 1)).astype(int)
        self.dots.setData(x, y, size=4 + lv * 22, brush=self.b_dot[cq])
        hot = lv > 0                             # sonuk halolari hic cizme
        self.halo.setData(x[hot], y[hot], size=10 + lv[hot] * 60, brush=self.b_halo[cq[hot]])
        # en guclu notalar arasinda baglar (akor geometrisi)
        act = np.where(semi > 0.6)[0]
        act = act[np.argsort(semi[act])[::-1]][:6]
        if len(act) > 1:
            px, py = [], []
            for i in range(len(act)):
                for j in range(i + 1, len(act)):
                    px += [x[act[i]], x[act[j]]]; py += [y[act[i]], y[act[j]]]
            self.links.setData(px, py)
        else:
            self.links.setData([], [])
        # vurus -> halka + parcacik
        for k in np.where((on > 0.3) & (semi > 0.7))[0][:5]:
            self.ring_list.append([x[k], y[k], 0.0])
            ang = np.random.rand(10) * 2 * np.pi; sp = 0.03 + np.random.rand(10) * 0.05
            newp = np.column_stack([np.full(10, x[k]), np.full(10, y[k]),
                                    np.cos(ang) * sp, np.sin(ang) * sp, np.ones(10)])
            self.part = np.vstack([self.part, newp])[-250:]
        self.ring_list = [[a, b, t + 1] for a, b, t in self.ring_list[-40:] if t < 30]
        if self.ring_list:
            R = np.array(self.ring_list)
            self.rings.setData(R[:, 0], R[:, 1], size=8 + R[:, 2] * 4,
                               pen=self.p_ring[R[:, 2].astype(int)])
        else:
            self.rings.setData([], [])
        if len(self.part):
            self.part[:, 0:2] += self.part[:, 2:4]; self.part[:, 2:4] *= 0.96
            self.part[:, 4] -= 0.025
            self.part = self.part[self.part[:, 4] > 0]
            pq = (np.round(self.part[:, 4] * 8) / 8 * (self.Q - 1)).astype(int)
            self.parts.setData(self.part[:, 0], self.part[:, 1], brush=self.b_part[pq])
        else:
            self.parts.setData([], [])
        rl = self.lbl_r
        for i, t in enumerate(self.lbls):
            a = np.pi / 2 - i * 2 * np.pi / 12 + self.rot
            t.setPos(rl * np.cos(a), rl * np.sin(a))
        k = int(np.argmax(semi))
        self.center.setText(f"{NOTES[self.midis[k] % 12]}{self.midis[k] // 12 - 1}"
                            if semi[k] > 0.5 else "")

class RhythmView(View):
    """Davul/bas gostergesi: 4 bant (Sub, Kick, Snare, Hi-hat) seviye cubugu,
    vurus aninda yanan 'pad'ler ve kick vuruslarindan BPM tahmini.
    Vurus tespiti: bant enerjisindeki ani artis (spectral flux) > uyarlanir esik."""
    name = "Ritim (Bas/Davul)"
    BANDS = [("SUB", 20, 60), ("KICK", 60, 150), ("SNARE", 180, 4000), ("HI-HAT", 6000, 16000)]
    def __init__(self):
        super().__init__()
        self.pl.hideAxis("left"); self.pl.showGrid(False, False)
        self.pl.setMouseEnabled(False, False)
        self.pl.setRange(xRange=(-0.6, 3.6), yRange=(-0.05, 1.75), padding=0)
        self.pl.getAxis("bottom").setTicks([[(i, b[0]) for i, b in enumerate(self.BANDS)]])
        self.pl.getAxis("bottom").setStyle(tickFont=QtGui.QFont(FONT, 10, QtGui.QFont.Bold))
        n = len(self.BANDS); self.x = np.arange(n)
        self.bars = pg.BarGraphItem(x=self.x, height=np.zeros(n), width=0.55, brush=RED_DEEP, pen=None)
        self.pl.addItem(self.bars)
        self.peak = pg.ScatterPlotItem(symbol="s", size=9, brush=pg.mkBrush(FG), pen=None)
        self.pl.addItem(self.peak)
        self.pads = pg.ScatterPlotItem(pxMode=True, antialias=True)
        self.pl.addItem(self.pads)
        self.bpm_t = pg.TextItem("", color=FG, anchor=(0.5, 0))
        self.bpm_t.setFont(QtGui.QFont(FONT, 18, QtGui.QFont.Bold)); self.pl.addItem(self.bpm_t)
        self.bpm_t.setPos(1.5, 1.75)
        self.level = np.zeros(n); self.hold = np.zeros(n); self.flash = np.zeros(n)
        self.prev = np.zeros(n); self.hist = [[] for _ in range(n)]
        self.last_hit = np.zeros(n); self.kicks = []
        self.clk = QtCore.QElapsedTimer(); self.clk.start()
        self.b_pad = [pg.mkBrush(255, int(59 + 196 * i / 15), int(66 + 189 * i / 15), int(40 + 215 * i / 15))
                      for i in range(16)]
        self.p_pad = pg.mkPen(RED, width=1.5)
        self.masks = None
    def update(self, A):
        now = self.clk.elapsed() / 1000
        f, mf = A["f_fast"], A["mf"]
        if self.masks is None or len(self.masks[0]) != len(f):
            self.masks = [(f >= lo) & (f < hi) for _, lo, hi in self.BANDS]
        e = np.array([np.sum(mf[m] ** 2) for m in self.masks])
        db = 10 * np.log10(e + 1e-12)
        lvl = np.clip((db + 50) / 50, 0, 1)                      # -50..0 dB -> 0..1
        self.level = np.maximum(lvl, self.level * 0.85)
        self.hold = np.maximum(self.level, self.hold - 0.006)
        # vurus tespiti: log-enerji artisi, son ~1 sn ortalama+std esiginin ustunde
        flux = np.maximum(db - self.prev, 0); self.prev = db
        for i in range(len(self.BANDS)):
            h = self.hist[i]; h.append(flux[i]); del h[:-60]
            thr = np.mean(h) + 1.8 * np.std(h) + 1.5
            gap = 0.09 if i < 2 else 0.06
            if flux[i] > thr and lvl[i] > 0.25 and now - self.last_hit[i] > gap:
                self.last_hit[i] = now; self.flash[i] = 1.0
                if i == 1:
                    self.kicks.append(now); self.kicks = [t for t in self.kicks if now - t < 8]
        self.flash *= 0.86
        self.bars.setOpts(height=self.level * 1.2,
                          brushes=[pg.mkBrush(RED_BRIGHT) if fl > 0.5 else pg.mkBrush(RED_DEEP)
                                   for fl in self.flash])
        self.peak.setData(self.x, self.hold * 1.2)
        q = np.clip((self.flash * 15).astype(int), 0, 15)
        self.pads.setData(self.x, np.full(len(self.x), 1.45), size=(28 + q * 2.4).astype(int),
                          brush=[self.b_pad[k] for k in q], pen=self.p_pad)
        # BPM: kick araliklarinin medyani, 70-180 araligina katlanir
        if len(self.kicks) >= 5:
            iv = np.diff(self.kicks); iv = iv[(iv > 0.25) & (iv < 2.0)]
            if len(iv) >= 3:
                bpm = 60 / np.median(iv)
                while bpm < 70: bpm *= 2
                while bpm > 180: bpm /= 2
                self.bpm_t.setText(f"{bpm:.0f} BPM")
        elif now - (self.kicks[-1] if self.kicks else 0) > 4:
            self.bpm_t.setText("— BPM")

VU_REFS = [("Otomatik", None), ("0 VU = -10 dBFS (modern)", -10), ("0 VU = -14 dBFS (Spotify)", -14),
           ("0 VU = -18 dBFS (stüdyo)", -18), ("0 VU = -6 dBFS (çok yüksek)", -6)]

class VURef:
    """VU panellerine referans secimi ekler. 'Otomatik': son ~10 sn ortalamasi -3 VU'ya oturur."""
    def init_ref(self):
        self.ref = VU_REFS[0][1]; self.auto_db = -12.0
        self.extra = QtWidgets.QComboBox(); self.extra.addItems([r[0] for r in VU_REFS])
        self.extra.setToolTip("0 VU'nun karsiligi: sarki surekli tepedeyse daha yuksek (-10 / -6) sec")
        self.extra.currentIndexChanged.connect(lambda i: setattr(self, "ref", VU_REFS[i][1]))
    def to_vu(self, rms, dt):
        d = 20 * np.log10(rms)
        if self.ref is None:                                   # otomatik: yavas ortalama
            if d > -60:
                self.auto_db += (d - self.auto_db) * (1 - np.exp(-dt / 10))
            return d - (self.auto_db + 3)
        return d - self.ref

class VUMeterView(View, VURef):
    """Analog konsol tarzi LED VU metre (L / R). 0 VU = -18 dBFS RMS.
    VU balistigi (~300 ms), tepe tutma (1.5 sn), 0 VU ustu kirmizi bolge, yanan bolumlerde hale."""
    name = "VU Metre"
    SEGS = [-20, -15, -10, -8, -7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3]     # her bolumun esigi (VU dB)
    MARKS = {-20: "-20", -10: "-10", -7: "-7", -5: "-5", -3: "-3", -2: "-2", -1: "-1",
             0: "0", 1: "+1", 2: "+2", 3: "+3"}
    COLS = (1.0, 3.6)
    def __init__(self):
        super().__init__()
        self.pl.hideAxis("left"); self.pl.hideAxis("bottom"); self.pl.showGrid(False, False)
        self.pl.setMouseEnabled(False, False)
        n = len(self.SEGS)
        self.pl.setRange(xRange=(-0.6, 4.6), yRange=(-2.2, n + 0.4), padding=0)
        self.y = np.arange(n) + 0.5
        hot = np.array(self.SEGS) > 0
        self.on_lo, self.on_hi = mix(RED, "#ffb000", 0.35), mix(RED_BRIGHT, "#ffffff", 0.15)
        self.off_lo, self.off_hi = mix(PANEL, RED_DEEP, 0.30), mix(PANEL, RED_DEEP, 0.55)
        self.b_on = [pg.mkBrush(*(self.on_hi if h else self.on_lo)) for h in hot]
        self.b_off = [pg.mkBrush(*(self.off_hi if h else self.off_lo)) for h in hot]
        self.b_glow = [pg.mkBrush(*(self.on_hi if h else self.on_lo), 60) for h in hot]
        self.b_none = pg.mkBrush(0, 0, 0, 0)
        self.bars, self.glows = [], []
        white = pg.mkPen(FG, width=2); redp = pg.mkPen(RED, width=3)
        for cx in self.COLS:
            g = pg.BarGraphItem(x=np.full(n, cx), y=self.y, height=0.98, width=1.25, brushes=[self.b_none] * n, pen=None)
            b = pg.BarGraphItem(x=np.full(n, cx), y=self.y, height=0.8, width=1.0, brushes=self.b_off, pen=None)
            self.pl.addItem(g); self.pl.addItem(b); self.glows.append(g); self.bars.append(b)
            # olcek: sol tarafta dikey cizgi + centikler + etiketler; 0 ustu kirmizi
            sx = cx - 0.9
            i0 = self.SEGS.index(0)
            self.pl.plot([sx, sx], [0, i0 + 0.5], pen=white)
            self.pl.plot([sx, sx], [i0 + 0.5, n], pen=redp)
            for i, v in enumerate(self.SEGS):
                big = v in self.MARKS
                self.pl.plot([sx - (0.22 if big else 0.12), sx], [i + 0.5, i + 0.5], pen=redp if v > 0 else white)
                if big:
                    tx = pg.TextItem(self.MARKS[v], color=RED if v > 0 else FG, anchor=(1, 0.5))
                    tx.setFont(QtGui.QFont(FONT, 8, QtGui.QFont.Bold)); tx.setPos(sx - 0.25, i + 0.5)
                    self.pl.addItem(tx)
            lab = pg.TextItem("L" if cx == self.COLS[0] else "R", color=MUTED, anchor=(0.5, 0))
            lab.setFont(QtGui.QFont(FONT, 12, QtGui.QFont.Bold)); lab.setPos(cx, -0.25); self.pl.addItem(lab)
        self.vu = np.full(2, -60.0); self.pk = np.full(2, -60.0); self.pk_t = np.zeros(2)
        self.last = [None, None]
        self.init_ref()
        self.clk = QtCore.QElapsedTimer(); self.clk.start(); self.t_prev = 0.0
    def update(self, A):
        now = self.clk.elapsed() / 1000; dt = max(1e-3, now - self.t_prev); self.t_prev = now
        # hizli balistik: yukselis ~40 ms, dusus ~150 ms (klasik VU'nun 300 ms'i cok yavas hissettiriyor)
        k_up, k_dn = 1 - np.exp(-dt / 0.04), 1 - np.exp(-dt / 0.15)
        for ch, x in enumerate((A["L"], A["R"])):
            rms = np.sqrt(np.mean(x[-1024:].astype(np.float64) ** 2)) + 1e-9   # ~21 ms pencere
            target = self.to_vu(rms, dt / 2)                       # dBFS -> VU (secili referans)
            self.vu[ch] += (target - self.vu[ch]) * (k_up if target > self.vu[ch] else k_dn)
            if self.vu[ch] >= self.pk[ch] or now - self.pk_t[ch] > 0.8:
                self.pk[ch] = self.vu[ch]; self.pk_t[ch] = now
            lit = sum(1 for s in self.SEGS if self.vu[ch] >= s)    # yanan bolum sayisi
            pk_i = sum(1 for s in self.SEGS if self.pk[ch] >= s) - 1
            key = (lit, pk_i)
            if key == self.last[ch]:                               # degismediyse boyama
                continue
            self.last[ch] = key
            n = len(self.SEGS)
            on = [i < lit or i == pk_i for i in range(n)]
            self.bars[ch].setOpts(brushes=[self.b_on[i] if on[i] else self.b_off[i] for i in range(n)])
            self.glows[ch].setOpts(brushes=[self.b_glow[i] if on[i] else self.b_none for i in range(n)])

class AnalogVUView(View, VURef):
    """Ibreli analog VU metre (L / R): krem kadran, VU olcegi (-20..+3), kirmizi bolge,
    mekanik ibre (yaylı sönüm), cam yansimasi, tepe lambasi. Tamamen QPainter ile cizilir."""
    name = "Analog VU (ibreli)"
    MARKS = [-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3]
    def __init__(self):                                   # PlotWidget yerine ozel widget
        self.widget = _NeedleWidget(self)
        self.init_ref()
        self.vu = np.full(2, -25.0); self.vel = np.zeros(2); self.peak_t = np.zeros(2)
        self.clk = QtCore.QElapsedTimer(); self.clk.start(); self.t_prev = 0.0
    def update(self, A):
        now = self.clk.elapsed() / 1000; dt = min(0.1, max(1e-3, now - self.t_prev)); self.t_prev = now
        for ch, x in enumerate((A["L"], A["R"])):
            rms = np.sqrt(np.mean(x[-2048:].astype(np.float64) ** 2)) + 1e-9
            target = max(-25.0, self.to_vu(rms, dt / 2))
            # kutle-yay-sonum: hafif asim (overshoot) yapan gercek ibre hissi
            acc = 180 * (target - self.vu[ch]) - 22 * self.vel[ch]
            self.vel[ch] += acc * dt; self.vu[ch] += self.vel[ch] * dt
            self.vu[ch] = min(max(self.vu[ch], -25.0), 5.0)
            if self.vu[ch] > 1.0:
                self.peak_t[ch] = now
        self.widget.lamp = [now - self.peak_t[c] < 0.25 for c in range(2)]
        self.widget.update()

def _vu_pos(v):
    """VU olcegi dogrusal degil: gerilime gore (10^(dB/20)) yerlestirilir, -20..+3 -> 0..1"""
    lo, hi = 10 ** (-20 / 20), 10 ** (3 / 20)
    return (10 ** (max(min(v, 5), -25) / 20) - lo) / (hi - lo)

class _NeedleWidget(QtWidgets.QWidget):
    def __init__(self, view):
        super().__init__(); self.v = view; self.lamp = [False, False]
        self.setMinimumSize(200, 120)
    def paintEvent(self, ev):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QtGui.QColor(PANEL))
        gap = 10; mw = (W - 3 * gap) / 2
        for ch in range(2):
            self.meter(p, QtCore.QRectF(gap + ch * (mw + gap), gap, mw, H - 2 * gap),
                       self.v.vu[ch], "LEFT" if ch == 0 else "RIGHT", self.lamp[ch])
        p.end()
    def meter(self, p, r, vu, label, lamp):
        import math
        # govde cercevesi + krem kadran (sicak arka isik)
        p.setPen(QtGui.QPen(QtGui.QColor("#0c0805"), 3))
        p.setBrush(QtGui.QColor("#3a2a1a")); p.drawRoundedRect(r, 10, 10)
        face = r.adjusted(8, 8, -8, -8)
        g = QtGui.QRadialGradient(face.center().x(), face.bottom(), face.width() * 0.9)
        g.setColorAt(0, QtGui.QColor("#fff1c8")); g.setColorAt(0.7, QtGui.QColor("#f0d692"))
        g.setColorAt(1, QtGui.QColor("#c9a55c"))
        p.setPen(QtGui.QPen(QtGui.QColor("#5a4026"), 1.5)); p.setBrush(QtGui.QBrush(g))
        p.drawRoundedRect(face, 6, 6)
        cx = face.center().x(); cy = face.bottom() - face.height() * 0.08
        R = min(face.width() * 0.46, face.height() * 0.78)
        a0, a1 = 140.0, 40.0                                         # derece, soldan saga
        def ang(v): return math.radians(a0 + (a1 - a0) * _vu_pos(v))
        def pt(a, rr): return QtCore.QPointF(cx + rr * math.cos(a), cy - rr * math.sin(a))
        # olcek yaylari: siyah (<0) + kirmizi (0..+3)
        arc = QtCore.QRectF(cx - R * 0.86, cy - R * 0.86, R * 1.72, R * 1.72)
        def deg16(v): return int((a0 + (a1 - a0) * _vu_pos(v)) * 16)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a120a"), 2)); p.drawArc(arc, deg16(-20), deg16(0) - deg16(-20))
        p.setPen(QtGui.QPen(QtGui.QColor("#c0181c"), 6, cap=QtCore.Qt.FlatCap))
        p.drawArc(arc, deg16(0), deg16(3) - deg16(0))
        # centikler + rakamlar
        f = QtGui.QFont("Georgia", max(7, int(R * 0.09))); f.setBold(True); p.setFont(f)
        for v in self.v.MARKS:
            a = ang(v); red = v > 0
            p.setPen(QtGui.QPen(QtGui.QColor("#c0181c" if red else "#1a120a"), 2))
            p.drawLine(pt(a, R * 0.86), pt(a, R * (0.97 if v in (-20, -10, -5, 0, 3) else 0.93)))
            if v in (-2, -1):                                   # sik bolgede rakam yazma
                continue
            tp = pt(a, R * 1.12); s = (f"+{v}" if v > 0 else str(v)).replace("-", "−")
            p.drawText(QtCore.QRectF(tp.x() - 20, tp.y() - 10, 40, 20), QtCore.Qt.AlignCenter, s)
        for v in np.arange(-20, 3.01, 0.5):                         # ince ara centikler
            if -10 <= v:
                a = ang(v); p.setPen(QtGui.QPen(QtGui.QColor("#c0181c" if v > 0 else "#3a2a1a"), 1))
                p.drawLine(pt(a, R * 0.86), pt(a, R * 0.89))
        # yuzde olcegi (alt) + yazilar
        p.setPen(QtGui.QColor("#3a2a1a"))
        f2 = QtGui.QFont("Georgia", max(10, int(R * 0.2))); f2.setBold(True); f2.setItalic(True); p.setFont(f2)
        p.drawText(QtCore.QRectF(cx - 60, cy - R * 0.55, 120, R * 0.3), QtCore.Qt.AlignCenter, "VU")
        f3 = QtGui.QFont("Georgia", max(6, int(R * 0.07))); p.setFont(f3)
        p.drawText(QtCore.QRectF(face.left() + 8, face.top() + 4, 80, 18), QtCore.Qt.AlignLeft, label)
        # tepe lambasi
        lc = QtGui.QColor("#ff2a1a" if lamp else "#5a1a12")
        lg = QtGui.QRadialGradient(face.right() - 18, face.top() + 16, 10)
        lg.setColorAt(0, QtGui.QColor("#ffd0a0") if lamp else lc); lg.setColorAt(1, lc)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a0f05"), 1)); p.setBrush(QtGui.QBrush(lg))
        p.drawEllipse(QtCore.QPointF(face.right() - 18, face.top() + 16), 6, 6)
        # ibre (golge + govde) ve pivot kapagi
        a = ang(vu)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 3))
        p.drawLine(QtCore.QPointF(cx + 3, cy + 3), pt(a, R * 0.98) + QtCore.QPointF(3, 3))
        p.setPen(QtGui.QPen(QtGui.QColor("#140c06"), 2))
        p.drawLine(QtCore.QPointF(cx, cy), pt(a, R * 0.98))
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor("#1a120a"))
        p.drawPie(QtCore.QRectF(cx - R * 0.16, cy - R * 0.16, R * 0.32, R * 0.32), 0, 180 * 16)
        # cam yansimasi
        gl = QtGui.QLinearGradient(face.topLeft(), face.bottomLeft())
        gl.setColorAt(0, QtGui.QColor(255, 255, 255, 70)); gl.setColorAt(0.45, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(QtGui.QBrush(gl)); p.drawRoundedRect(face, 6, 6)

class CRTScopeView(View):
    """Yesil fosfor CRT osiloskop: 10x8 bolmeli izgara, tetiklemeli iz,
    son taramalarin sonerek kalan izi (persistence) ve hafif parlama."""
    name = "CRT Osiloskop"
    PHOS = (57, 255, 136)
    def __init__(self):
        super().__init__()
        self.widget.setBackground("#020a05")
        pl = self.pl; pl.hideAxis("left"); pl.hideAxis("bottom"); pl.showGrid(False, False)
        pl.setMouseEnabled(False, False); pl.setRange(xRange=(0, 10), yRange=(-4, 4), padding=0)
        for x in range(11):
            pl.addItem(pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(*self.PHOS, 70 if x == 5 else 28)))
        for y in range(-4, 5):
            pl.addItem(pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(*self.PHOS, 70 if y == 0 else 28)))
        for x in np.arange(0, 10.01, 0.2):                  # orta eksen uzerinde ince centikler
            pl.plot([x, x], [-0.1, 0.1], pen=pg.mkPen(*self.PHOS, 70))
        self.N = 1024
        self.x = np.linspace(0, 10, self.N)
        self.hist = []
        self.ghost = [pl.plot(pen=pg.mkPen(*self.PHOS, a)) for a in (25, 45, 70)]   # eski taramalar
        self.glow = pl.plot(pen=pg.mkPen(*self.PHOS, 55, width=3))
        self.beam = pl.plot(pen=pg.mkPen(200, 255, 220, 255, width=1))
        self.lbl = pg.TextItem("", color=self.PHOS, anchor=(0, 0))
        self.lbl.setFont(QtGui.QFont("Consolas", 9)); pl.addItem(self.lbl); self.lbl.setPos(0.1, 3.95)
        # tarama cizgileri: tek goruntu (her karede cizilmez, ucuz)
        sl = np.zeros((1, 160)); sl[0, ::2] = 1
        img = pg.ImageItem(sl, levels=(0, 1)); img.setRect(QtCore.QRectF(0, -4, 10, 8)); img.setOpacity(0.10)
        img.setLookupTable(np.array([[0, 0, 0, 0], [0, 0, 0, 255]], dtype=np.ubyte)); pl.addItem(img)
    def update(self, A):
        m = (A["L"] + A["R"]) * 0.5
        seg = m[-4096:-self.N]
        idx = np.where((seg[:-1] < 0) & (seg[1:] >= 0))[0]
        s = len(m) - 4096 + (idx[-1] if len(idx) else 0)
        y = m[s:s + self.N] * 8                               # 0.125 / bolme
        self.hist.append(y); del self.hist[:-4]
        for g, h in zip(self.ghost, self.hist[:-1][::-1][:3][::-1]):
            g.setData(self.x, h)
        self.glow.setData(self.x, y); self.beam.setData(self.x, y)
        self.lbl.setText(f"CH1  0.125/div   {self.N / RATE * 100:.2f} ms/div   TRIG ↑")

class LEDSpectrumView(View):
    """Eski hi-fi grafik analizor: 31 bant (1/3 oktav, ISO), her bant 20 LED.
    Alt bolgeler amber/yesil, ust bolgeler sari ve kirmizi. Tepe tutma LED'i, hizli atak / yavas dusus."""
    name = "LED Spektrum (31 bant)"
    NSEG = 20
    def __init__(self):
        super().__init__()
        self.cf = 1000 * 2 ** (np.arange(-17, 14) / 3)            # 20 Hz .. 20 kHz
        nb = len(self.cf)
        pl = self.pl; pl.hideAxis("left"); pl.showGrid(False, False); pl.setMouseEnabled(False, False)
        pl.setRange(xRange=(-0.7, nb - 0.3), yRange=(-0.6, self.NSEG + 0.2), padding=0)
        lab = {31: "31", 63: "63", 125: "125", 250: "250", 500: "500", 1000: "1k", 2000: "2k",
               4000: "4k", 8000: "8k", 16000: "16k"}
        ticks = []
        for i, f in enumerate(self.cf):
            for k, s in lab.items():
                if abs(np.log2(f / k)) < 0.1:
                    ticks.append((i, s))
        pl.getAxis("bottom").setTicks([ticks])
        xs, ys = np.meshgrid(np.arange(nb), np.arange(self.NSEG))
        self.xs, self.ys = xs.ravel(), ys.ravel() + 0.5
        self.cells = pg.ScatterPlotItem(symbol="s", pxMode=False, size=0.7, pen=None)
        pl.addItem(self.cells)
        retro = THEME == "Retro Analog"
        def seg_col(j):                                          # j: 0..NSEG-1 alttan uste
            if retro or True:
                if j >= self.NSEG - 3: return (255, 52, 30)          # kirmizi
                if j >= self.NSEG - 7: return (255, 196, 40)         # sari
                return (255, 150, 40) if retro else rgb(RED)         # amber / tema
        self.on = [pg.mkBrush(*seg_col(j)) for j in range(self.NSEG)]
        self.off = [pg.mkBrush(*mix(PANEL, "#%02x%02x%02x" % seg_col(j), 0.16)) for j in range(self.NSEG)]
        self.level = np.zeros(nb); self.peak = np.zeros(nb); self.pk_t = np.zeros(nb)
        self.clk = QtCore.QElapsedTimer(); self.clk.start(); self.t_prev = 0.0
        self.edges = None
    def update(self, A):
        f, db = A["f_big"], A["db_big"]
        if self.edges is None or len(self.edges[0]) != len(f):
            lo, hi = self.cf * 2 ** (-1 / 6), self.cf * 2 ** (1 / 6)
            self.edges = [(f >= l) & (f < h) for l, h in zip(lo, hi)]
        pw = 10 ** (db / 10)
        band = np.array([10 * np.log10(pw[m].sum() + 1e-12) if m.any() else
                         np.interp(np.log10(c), np.log10(f), db) for m, c in zip(self.edges, self.cf)])
        target = np.clip((band + 60) / 60, 0, 1) * self.NSEG          # -60..0 dB -> 0..20 LED
        now = self.clk.elapsed() / 1000; dt = max(1e-3, now - self.t_prev); self.t_prev = now
        self.level = np.where(target > self.level, target, np.maximum(target, self.level - 30 * dt))
        hold = (self.level >= self.peak) | (now - self.pk_t > 1.0)
        self.peak = np.where(hold, self.level, np.maximum(self.peak - 8 * dt, self.level))
        self.pk_t = np.where(self.level >= self.peak, now, self.pk_t)
        lit = self.level.astype(int); pk = np.minimum(self.peak.astype(int), self.NSEG - 1)
        j = (self.ys - 0.5).astype(int); x = self.xs
        on = (j < lit[x]) | ((j == pk[x]) & (self.peak[x] > 0.5))
        self.cells.setData(self.xs, self.ys, brush=[self.on[jj] if o else self.off[jj] for jj, o in zip(j, on)])

class DrumTrailView(View):
    """Davul izi: kick / snare / hi-hat vuruslari kendi seritlerinde zamanla akar
    (Melodi Izi gibi, sagda 'simdi'). Nokta boyu + parlaklik = vurus gucu.
    Arkada bulunan tempoya gore vurus cizgileri; her 4. cizgi kalin."""
    name = "Davul Izi"
    SPAN = 6.0
    LANES = [("KICK", "o", 22), ("SNARE", "s", 16), ("HI-HAT", "t", 11)]   # ad, sembol, en buyuk boy
    def __init__(self):
        super().__init__()
        pl = self.pl; pl.setMouseEnabled(False, False); pl.showGrid(False, False)
        pl.setRange(xRange=(-self.SPAN, 0.15), yRange=(-0.6, 2.6), padding=0)
        pl.getAxis("left").setTicks([[(2 - i, n) for i, (n, _, _) in enumerate(self.LANES)]])
        pl.setLabel("bottom", "saniye")
        for y in (0.5, 1.5):
            pl.addItem(pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(LINE)))
        self.beats = pl.plot(pen=pg.mkPen(*rgb(MUTED), 45), connect="pairs")
        self.bars = pl.plot(pen=pg.mkPen(*rgb(MUTED), 110), connect="pairs")
        pl.addItem(pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(RED_BRIGHT, width=1)))   # simdi
        self.sc = []
        for i, (_, sym, _) in enumerate(self.LANES):
            s = pg.ScatterPlotItem(symbol=sym, pen=None); pl.addItem(s); self.sc.append(s)
        self.b = np.array([pg.mkBrush(*[int(c) for c in LUT[int(70 + 185 * k / 15)][:3]])
                           for k in range(16)], dtype=object)
        self.info = pg.TextItem("", color=FG, anchor=(1, 0)); self.info.setFont(QtGui.QFont(FONT, 13, QtGui.QFont.Bold))
        pl.addItem(self.info); self.info.setPos(0.1, 2.6)
    def update(self, A):
        now = now_audio()
        hs = tracker.strengths(now - self.SPAN)
        for i, (_, _, big) in enumerate(self.LANES):
            h = [x for x in hs if x[1] == i]
            if not h:
                self.sc[i].setData([], []); continue
            a = np.array(h); x = a[:, 0] - now; s = a[:, 2]
            q = np.clip((s * 15).astype(int), 0, 15)
            # yeni vurus kisa sure "patlar": son 120 ms icindekiler daha buyuk
            fresh = np.clip(1 - (-x) / 0.12, 0, 1)
            size = (big * (0.45 + 0.55 * s) * (1 + 0.6 * fresh)).astype(int)
            self.sc[i].setData(x, np.full(len(x), 2 - i), size=size, brush=self.b[q])
        bpm, beat0, _ = tracker.snapshot()
        if bpm:
            beat = 60 / bpm
            k0 = int(np.floor((now - self.SPAN - beat0) / beat)); k1 = int(np.ceil((now - beat0) / beat)) + 1
            ks = np.arange(k0, k1); xs = beat0 + ks * beat - now
            keep = (xs >= -self.SPAN) & (xs <= 0.15); ks, xs = ks[keep], xs[keep]
            def pairs(xx):
                return np.repeat(xx, 2), np.tile([-0.6, 2.6], len(xx))
            self.beats.setData(*pairs(xs[ks % 4 != 0])); self.bars.setData(*pairs(xs[ks % 4 == 0]))
            self.info.setText(f"{bpm:.0f} BPM")
        else:
            self.beats.setData([], []); self.bars.setData([], []); self.info.setText("Tempo araniyor…")


# ---------------- SPOTIFY (Web API, OAuth PKCE) ----------------
class SpotifyClient:
    """Spotify Web API istemcisi. Giris: OAuth 'Authorization Code + PKCE' (sifre/secret yok).
    Ayar + token: ~/.falcon_audio/spotify.json  (repo disinda - GitHub'a gitmez).
    Arka plan is parcacigi ~1 sn'de bir 'su an calan'i ceker; arayuz sadece self.state'i okur."""
    REDIRECT = "http://127.0.0.1:8888/callback"
    SCOPES = "user-read-currently-playing user-read-playback-state user-modify-playback-state"
    def __init__(self):
        import os, json
        self.dir = os.path.join(os.path.expanduser("~"), ".falcon_audio")
        self.path = os.path.join(self.dir, "spotify.json")
        self.cfg = {}
        try:
            self.cfg = json.load(open(self.path, encoding="utf8"))
        except Exception:
            pass
        self.lk = threading.Lock()
        self.state = {"status": "baglanmadi" if not self.cfg.get("refresh_token") else "baglaniyor"}
        self.art_cache = {}
        self.running = False
    # ---- kalici ayar ----
    def save(self):
        import os, json
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path, "w", encoding="utf8") as f:
            json.dump(self.cfg, f)
    # ---- http ----
    def _req(self, method, url, data=None, headers=None, form=False):
        import urllib.request, urllib.parse, json
        body = None
        h = dict(headers or {})
        if data is not None:
            if form:
                body = urllib.parse.urlencode(data).encode(); h["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(data).encode(); h["Content-Type"] = "application/json"
        elif method in ("PUT", "POST"):
            body = b""
        r = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=8) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except Exception:
                return e.code, None
    # ---- giris (PKCE) ----
    def login(self, client_id):
        """Tarayicida Spotify izin sayfasini acar, 127.0.0.1:8888'de donusu bekler."""
        threading.Thread(target=self._login, args=(client_id.strip(),), daemon=True).start()
    def _login(self, client_id):
        import secrets, hashlib, base64, urllib.parse, webbrowser, http.server
        self._set(status="giris bekleniyor (tarayicida izin ver)")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        st = secrets.token_urlsafe(16)
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(dict(
            client_id=client_id, response_type="code", redirect_uri=self.REDIRECT,
            code_challenge_method="S256", code_challenge=challenge, scope=self.SCOPES, state=st))
        got = {}
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(s):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(s.path).query)
                got.update({k: v[0] for k, v in q.items()})
                s.send_response(200); s.send_header("Content-Type", "text/html; charset=utf-8"); s.end_headers()
                ok = "code" in q
                s.wfile.write(("<h2 style='font-family:sans-serif'>" +
                               ("FALCON//AUDIO Spotify'a baglandi. Bu sekmeyi kapatabilirsin." if ok
                                else "Baglanti reddedildi.") + "</h2>").encode())
            def log_message(s, *a): pass
        try:
            srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
        except OSError:
            self._set(status="hata: 8888 portu kullanimda"); return
        srv.timeout = 180
        webbrowser.open(url)
        srv.handle_request(); srv.server_close()
        if got.get("state") != st or "code" not in got:
            self._set(status="giris iptal / reddedildi: " + got.get("error", "zaman asimi")); return
        code, tok = self._req("POST", "https://accounts.spotify.com/api/token", form=True, data=dict(
            grant_type="authorization_code", code=got["code"], redirect_uri=self.REDIRECT,
            client_id=client_id, code_verifier=verifier))
        if code != 200 or not tok:
            self._set(status=f"token alinamadi ({code}): {tok}"); return
        self.cfg.update(client_id=client_id, refresh_token=tok.get("refresh_token"))
        self.access, self.exp = tok["access_token"], self._now() + tok.get("expires_in", 3600) - 60
        self.save(); self._set(status="bagli")
        self.start()
    # ---- token ----
    @staticmethod
    def _now():
        import time; return time.time()
    def token(self):
        if getattr(self, "access", None) and self._now() < self.exp:
            return self.access
        if not self.cfg.get("refresh_token"):
            return None
        code, tok = self._req("POST", "https://accounts.spotify.com/api/token", form=True, data=dict(
            grant_type="refresh_token", refresh_token=self.cfg["refresh_token"], client_id=self.cfg["client_id"]))
        if code != 200 or not tok:
            self._set(status=f"oturum yenilenemedi ({code}) - yeniden baglan"); return None
        self.access, self.exp = tok["access_token"], self._now() + tok.get("expires_in", 3600) - 60
        if tok.get("refresh_token"):                         # Spotify yenisini verebilir
            self.cfg["refresh_token"] = tok["refresh_token"]; self.save()
        return self.access
    def api(self, method, path, data=None):
        tk = self.token()
        if not tk:
            return None, None
        return self._req(method, "https://api.spotify.com/v1" + path, data=data,
                         headers={"Authorization": "Bearer " + tk})
    # ---- yoklama ----
    def _set(self, **kw):
        with self.lk:
            self.state = {**self.state, **kw}
    def get(self):
        with self.lk:
            return dict(self.state)
    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._poll, daemon=True).start()
    def _poll(self):
        import time, urllib.request
        while True:
            try:
                code, js = self.api("GET", "/me/player/currently-playing?additional_types=episode")
                if code == 200 and js and js.get("item"):
                    it = js["item"]
                    imgs = (it.get("album") or it.get("show") or {}).get("images") or []
                    art_url = imgs[0]["url"] if imgs else None
                    if art_url and art_url not in self.art_cache:
                        self.art_cache = {art_url: urllib.request.urlopen(art_url, timeout=8).read()}
                    self._set(status="bagli", title=it.get("name", ""),
                              artist=", ".join(a["name"] for a in it.get("artists", [])) or
                                     (it.get("show") or {}).get("publisher", ""),
                              album=(it.get("album") or {}).get("name", ""),
                              playing=js.get("is_playing", False), progress=js.get("progress_ms", 0),
                              duration=it.get("duration_ms", 1), art=self.art_cache.get(art_url),
                              t_fetch=time.time())
                elif code in (200, 204):
                    self._set(status="bagli", title="", playing=False)
                elif code is not None:
                    self._set(status=f"API hatasi {code}")
            except Exception as e:
                self._set(status=f"ag hatasi: {e}")
            time.sleep(1.0)
    def control(self, what):
        def go():
            path = {"play": ("PUT", "/me/player/play"), "pause": ("PUT", "/me/player/pause"),
                    "next": ("POST", "/me/player/next"), "prev": ("POST", "/me/player/previous")}[what]
            code, js = self.api(*path)
            if code == 403:
                self._set(note="Kontrol icin Spotify Premium gerekli")
            elif code == 404:
                self._set(note="Aktif Spotify cihazi yok")
            elif code and code >= 300:
                self._set(note=f"Kontrol hatasi {code}")
            else:
                self._set(note="")
        threading.Thread(target=go, daemon=True).start()

spotify = SpotifyClient()

class SpotifyView(View):
    """Spotify 'su an calan' paneli: kapak, sarki/sanatci/albüm, ilerleme, kontrol dugmeleri."""
    name = "Spotify"
    def __init__(self):
        W = QtWidgets.QWidget(); W.setObjectName("spotify")
        W.setStyleSheet(f"QWidget#spotify {{ background:{PANEL}; }} QLabel {{ background:transparent; }}")
        self.widget = W
        lay = QtWidgets.QHBoxLayout(W); lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(14)
        self.art = QtWidgets.QLabel(); self.art.setAlignment(QtCore.Qt.AlignCenter)
        self.art.setMinimumSize(90, 90); self.art.setStyleSheet(f"border:1px solid {LINE};")
        self.art.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        lay.addWidget(self.art, 2)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(4); lay.addLayout(col, 5)
        self.title = QtWidgets.QLabel("—"); self.title.setStyleSheet(f"color:{FG}; font-size:20px; font-weight:bold;")
        self.artist = QtWidgets.QLabel(""); self.artist.setStyleSheet(f"color:{RED_BRIGHT}; font-size:14px;")
        self.album = QtWidgets.QLabel(""); self.album.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        for w in (self.title, self.artist, self.album):
            w.setWordWrap(True); col.addWidget(w)
        col.addStretch(1)
        self.bar = QtWidgets.QProgressBar(); self.bar.setRange(0, 1000); self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(f"QProgressBar {{ background:{PANEL2}; border:none; border-radius:3px; }}"
                               f"QProgressBar::chunk {{ background:{RED}; border-radius:3px; }}")
        col.addWidget(self.bar)
        tl = QtWidgets.QHBoxLayout(); self.t0 = QtWidgets.QLabel("0:00"); self.t1 = QtWidgets.QLabel("0:00")
        for w in (self.t0, self.t1):
            w.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        tl.addWidget(self.t0); tl.addStretch(1); tl.addWidget(self.t1); col.addLayout(tl)
        btns = QtWidgets.QHBoxLayout(); btns.addStretch(1)
        # emoji glifleri Windows'ta mavi emoji olarak cikiyor -> Qt'nin standart medya simgeleri
        sty = QtWidgets.QApplication.style()
        self.ic = {k: sty.standardIcon(getattr(QtWidgets.QStyle, v)) for k, v in
                   dict(prev="SP_MediaSkipBackward", play="SP_MediaPlay", pause="SP_MediaPause",
                        next="SP_MediaSkipForward").items()}
        self.b_prev, self.b_play, self.b_next = (QtWidgets.QPushButton() for _ in range(3))
        for b, k in ((self.b_prev, "prev"), (self.b_play, "play"), (self.b_next, "next")):
            b.setIcon(self.ic[k]); b.setIconSize(QtCore.QSize(18, 18))
            b.setFixedSize(46, 34); b.setStyleSheet("padding:0;"); btns.addWidget(b)
        btns.addStretch(1); col.addLayout(btns)
        self.b_prev.clicked.connect(lambda: spotify.control("prev"))
        self.b_next.clicked.connect(lambda: spotify.control("next"))
        self.b_play.clicked.connect(lambda: spotify.control("pause" if self.playing else "play"))
        self.status = QtWidgets.QLabel(""); self.status.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.status.setWordWrap(True); col.addWidget(self.status)
        self.extra = QtWidgets.QPushButton("BAGLAN"); self.extra.setToolTip("Spotify hesabina baglan")
        self.extra.clicked.connect(self.connect)
        self.playing = False; self.art_key = None; self.last = None
        if spotify.cfg.get("refresh_token"):
            spotify.start()
    def connect(self):
        cid, ok = QtWidgets.QInputDialog.getText(
            self.widget, "Spotify'a baglan",
            "developer.spotify.com/dashboard'da olusturdugun uygulamanin Client ID'si:\n"
            "(Redirect URI olarak  http://127.0.0.1:8888/callback  ekli olmali)",
            text=spotify.cfg.get("client_id", ""))
        if ok and cid.strip():
            spotify.login(cid)
    @staticmethod
    def fmt(ms):
        s = int(ms / 1000); return f"{s // 60}:{s % 60:02d}"
    def update(self, A):
        import time
        s = spotify.get()
        st = s.get("status", "")
        if st != "bagli" or not s.get("title"):
            self.title.setText("Spotify" if st != "bagli" else "Şu an bir şey çalmıyor")
            msg = {"baglanmadi": "Bağlı değil. Başlıktaki BAĞLAN düğmesine bas."}.get(st, st)
            self.status.setText(msg + ("  " + s.get("note", "") if s.get("note") else ""))
            if st != "bagli":
                self.artist.setText(""); self.album.setText("")
            return
        prog = s["progress"] + ((time.time() - s["t_fetch"]) * 1000 if s["playing"] else 0)
        prog = min(prog, s["duration"])
        key = (s["title"], s["artist"], s["playing"])
        if key != self.last:
            self.last = key
            self.title.setText(s["title"]); self.artist.setText(s["artist"]); self.album.setText(s["album"])
            self.playing = s["playing"]; self.b_play.setIcon(self.ic["pause" if self.playing else "play"])
        self.bar.setValue(int(1000 * prog / max(1, s["duration"])))
        self.t0.setText(self.fmt(prog)); self.t1.setText(self.fmt(s["duration"]))
        self.status.setText(s.get("note", ""))
        if s.get("art") and id(s["art"]) != self.art_key or (self.art_key and self.art.pixmap() and
                                                               self.art.pixmap().width() != min(self.art.width(), self.art.height())):
            self.art_key = id(s.get("art"))
            pm = QtGui.QPixmap(); pm.loadFromData(s["art"] or b"")
            side = min(self.art.width(), self.art.height())
            if not pm.isNull() and side > 10:
                self.art.setPixmap(pm.scaled(side, side, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

VIEWS = [ScopeView, SpectrumView, ChromaView, NoteOctaveView, WaterfallView,
         SpiralView, OctaveEnergyView, RhythmView, WideChromaView, MelodyView, DrumGridView, VUMeterView, AnalogVUView, CRTScopeView, LEDSpectrumView, DrumTrailView, SpotifyView]

# ---------------- PANEL + ARAYUZ ----------------
class Panel(QtWidgets.QFrame):
    def __init__(self, default):
        super().__init__()
        self.setObjectName("panel")
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6, 4, 6, 6); lay.setSpacing(3)
        head = QtWidgets.QHBoxLayout()
        dot = QtWidgets.QLabel("■"); dot.setStyleSheet(f"color:{RED};"); self.dot = dot
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems([v.name for v in VIEWS])
        close = QtWidgets.QToolButton(); close.setText("✕"); close.setObjectName("close")
        close.setToolTip("Paneli kapat (ust cubuktaki + PANEL ile geri gelir)")
        close.clicked.connect(self.hide)
        head.addWidget(dot); head.addWidget(self.combo); head.addStretch(1); head.addWidget(close)
        self.head = head
        lay.addLayout(head)
        self.holder = QtWidgets.QStackedLayout(); lay.addLayout(self.holder, 1)
        self.view = None
        self.combo.currentIndexChanged.connect(self.set_view)
        self.combo.setCurrentIndex(VIEWS.index(default))
        if self.view is None:
            self.set_view(VIEWS.index(default))
    def paintEvent(self, ev):
        super().paintEvent(ev)
        if THEME != "Retro Analog":
            return
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing)
        W, H = self.width(), self.height()
        for cx, cy in ((9, H - 9), (W - 9, H - 9)):          # alt koselere vida (ustte baslik var)
            g = QtGui.QRadialGradient(cx - 1.5, cy - 1.5, 6)
            g.setColorAt(0, QtGui.QColor("#e8dcc0")); g.setColorAt(1, QtGui.QColor("#6a5a40"))
            p.setPen(QtGui.QPen(QtGui.QColor("#1a120a"), 1)); p.setBrush(QtGui.QBrush(g))
            p.drawEllipse(QtCore.QPointF(cx, cy), 4.5, 4.5)
            p.setPen(QtGui.QPen(QtGui.QColor("#2a1f12"), 1.4))
            p.drawLine(QtCore.QPointF(cx - 3, cy + 1.5), QtCore.QPointF(cx + 3, cy - 1.5))
        p.end()
    def set_view(self, i):
        if self.view:
            self.view.dispose()
            if self.view.extra is not None:
                self.head.removeWidget(self.view.extra); self.view.extra.deleteLater()
            self.holder.removeWidget(self.view.widget); self.view.widget.deleteLater()
        self.view = VIEWS[i](); self.holder.addWidget(self.view.widget)
        if self.view.extra is not None:            # gorunume ozel ayar (orn. melodi oktavi)
            self.head.insertWidget(2, self.view.extra)
        self.dot.setStyleSheet(f"color:{RED};")

def build_qss():
    return f"""
QWidget#root {{ background:transparent; }}
QWidget#spacer {{ background:transparent; }}
QWidget {{ background:{INK}; color:{FG}; font-family:'{FONT}','Segoe UI'; font-size:12px; }}
QFrame#panel {{ background:{PANEL}; border:{"3px ridge " + LINE if THEME == "Retro Analog" else "1px solid " + LINE};
    border-radius:{"8px" if THEME == "Retro Analog" else "4px"}; }}
QComboBox, QSpinBox {{ background:{PANEL2}; border:1px solid {LINE}; padding:3px 8px; border-radius:3px;
    text-transform:uppercase; letter-spacing:1px; }}
QComboBox:hover {{ border-color:{RED}; }}
QComboBox QAbstractItemView {{ background:{PANEL2}; selection-background-color:{RED}; }}
QSplitter::handle {{ background:{INK}; }}
QSplitter::handle:hover {{ background:{RED_DEEP}; }}
QLabel#brand {{ font-size:17px; font-weight:bold; letter-spacing:3px; }}
QLabel#muted {{ color:{MUTED}; }}
QPushButton {{ background:{RED}; border:none; padding:5px 12px; border-radius:3px; font-weight:bold; }}
QPushButton:hover {{ background:{RED_BRIGHT}; }}
QToolButton#close {{ background:transparent; color:{MUTED}; border:none; font-size:14px; padding:0 6px; }}
QToolButton#close:hover {{ color:{FG}; background:{RED}; border-radius:3px; }}
QPushButton#ghost {{ background:{PANEL2}; border:1px solid {LINE}; }}
QPushButton#ghost:hover {{ border-color:{RED}; background:{PANEL2}; }}
QPushButton#toggle {{ background:{PANEL2}; border:1px solid {LINE}; color:{MUTED}; }}
QPushButton#toggle:checked {{ background:{RED}; border-color:{RED}; color:{FG}; }}
QToolBar {{ background:{INK}; border-bottom:1px solid {LINE}; spacing:8px; padding:6px; }}
""" + (RETRO_QSS if THEME == "Retro Analog" else "")

RETRO_QSS = """
QToolBar { background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #8f8a80, stop:0.5 #c9c3b6, stop:1 #7d776c);
           border-bottom:3px solid #3a2a18; }
QToolBar QLabel { color:#2a1c0e; background:transparent; font-weight:bold; }
QToolBar QLabel#brand { color:#1a0f05; }
QToolBar QLabel#muted { color:#3a2a18; }
QComboBox, QSpinBox { background:#efe2c2; color:#2a1c0e; border:2px outset #8a7350; border-radius:4px; }
QComboBox QAbstractItemView { background:#efe2c2; color:#2a1c0e; selection-background-color:#c46a1c; }
QPushButton { background:qradialgradient(cx:0.5,cy:0.4,radius:0.7, stop:0 #e0a050, stop:1 #8a4a14);
              color:#fff3dc; border:2px outset #6e3a10; border-radius:6px; }
QPushButton:pressed, QPushButton:checked { border-style:inset; }
QPushButton#toggle:!checked { background:#5a4329; color:#d8c8a8; }
"""
QSS = build_qss()

class EdgeGlow(QtWidgets.QWidget):
    """Pencerenin ustunde, fareyi gecirgen ince katman: sadece kenar ve koselerde
    iceri dogru sonen beyaz parlama ciziyor. Yalnizca kenar seridi yeniden boyanir (FPS dostu)."""
    W = 70   # parlama derinligi (px)
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.level = 0.0
        parent.installEventFilter(self)
        self.setGeometry(parent.rect()); self.raise_()
    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Resize:
            self.setGeometry(obj.rect()); self.raise_()
        return False
    def border_region(self):
        r, w = self.rect(), self.W
        return QtGui.QRegion(r).subtracted(QtGui.QRegion(r.adjusted(w, w, -w, -w)))
    def set_level(self, a):
        if a == self.level:
            return
        self.level = a
        self.update(self.border_region())
    def paintEvent(self, ev):
        if self.level <= 0:
            return
        p = QtGui.QPainter(self)
        r, w = self.rect(), self.W
        a = int(255 * self.level)
        def grad(x1, y1, x2, y2):
            g = QtGui.QLinearGradient(x1, y1, x2, y2)
            g.setColorAt(0.0, QtGui.QColor(255, 255, 255, a))
            g.setColorAt(0.25, QtGui.QColor(*mix(RED_BRIGHT, "#ffffff", 0.4), int(a * 0.55)))
            g.setColorAt(1.0, QtGui.QColor(*rgb(RED), 0))
            return QtGui.QBrush(g)
        W_, H_ = r.width(), r.height()
        p.fillRect(0, 0, W_, w, grad(0, 0, 0, w))                 # ust
        p.fillRect(0, H_ - w, W_, w, grad(0, H_, 0, H_ - w))      # alt
        p.fillRect(0, 0, w, H_, grad(0, 0, w, 0))                 # sol
        p.fillRect(W_ - w, 0, w, H_, grad(W_, 0, W_ - w, 0))      # sag
        # koseler: ekstra radyal parlama
        for cx, cy in ((0, 0), (W_, 0), (0, H_), (W_, H_)):
            g = QtGui.QRadialGradient(cx, cy, w * 2.2)
            g.setColorAt(0.0, QtGui.QColor(255, 255, 255, a))
            g.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
            p.fillRect(QtCore.QRectF(cx - w * 2.2, cy - w * 2.2, w * 4.4, w * 4.4), QtGui.QBrush(g))
        p.end()

class Main(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FALCON // Ses Gorsellestirici")
        self.resize(1500, 950)
        self.an = Analyzer()
        tb = QtWidgets.QToolBar(); tb.setMovable(False); self.addToolBar(tb)
        b = QtWidgets.QLabel("FALCON<span style='color:%s'>//</span>AUDIO" % RED)
        b.setObjectName("brand"); tb.addWidget(b); self.brand = b
        self.c_theme = QtWidgets.QComboBox(); self.c_theme.addItems(list(THEMES))
        self.c_theme.setToolTip("Tema"); self.c_theme.currentTextChanged.connect(self.set_theme)
        tb.addWidget(self.c_theme); tb.addSeparator()
        def lab(t):
            l = QtWidgets.QLabel(t); l.setObjectName("muted"); tb.addWidget(l)
        lab("FFT"); self.c_big = QtWidgets.QComboBox()
        self.c_big.addItems(["4096", "8192", "16384", "32768"]); self.c_big.setCurrentText("8192")
        tb.addWidget(self.c_big)
        lab("Nota hizi"); self.c_fast = QtWidgets.QComboBox()
        self.c_fast.addItems(["Cok hizli (1024)", "Hizli (2048)", "Dengeli (4096)", "Hassas (8192)"])
        self.c_fast.setCurrentIndex(1); tb.addWidget(self.c_fast)
        lab("Dusus"); self.c_decay = QtWidgets.QComboBox()
        self.c_decay.addItems(["Ani", "Hizli", "Orta", "Yavas"]); self.c_decay.setCurrentIndex(1)
        tb.addWidget(self.c_decay)
        lab("Waterfall"); self.s_wf = QtWidgets.QSpinBox()
        self.s_wf.setRange(1, WF_SEC_MAX); self.s_wf.setValue(WaterfallView.seconds)
        self.s_wf.setSuffix(" sn"); tb.addWidget(self.s_wf)
        self.s_wf.valueChanged.connect(self.set_wf)
        dev_b = QtWidgets.QPushButton("CIHAZ"); dev_b.clicked.connect(self.pick_device)
        tb.addWidget(dev_b)
        self.dev_lbl = QtWidgets.QLabel(""); self.dev_lbl.setObjectName("muted"); tb.addWidget(self.dev_lbl)
        sp = QtWidgets.QWidget(); sp.setObjectName("spacer"); sp.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                                   QtWidgets.QSizePolicy.Preferred); tb.addWidget(sp)
        self.b_flash = QtWidgets.QPushButton("FLAS: ACIK"); self.b_flash.setCheckable(True)
        self.b_flash.setChecked(True); self.b_flash.setObjectName("toggle")
        self.b_flash.setToolTip("Kick vurusunda pencere kenarlarinda beyaz parlama")
        self.b_flash.toggled.connect(lambda on: self.b_flash.setText("FLAS: " + ("ACIK" if on else "KAPALI")))
        tb.addWidget(self.b_flash)
        self.s_flash = QtWidgets.QSpinBox()
        self.s_flash.setRange(10, 100); self.s_flash.setSingleStep(10); self.s_flash.setValue(20)
        self.s_flash.setSuffix(" %"); self.s_flash.setToolTip("Parlama siddeti")
        tb.addWidget(self.s_flash)
        lab("Klavye"); self.c_kbd = QtWidgets.QComboBox()
        self.c_kbd.addItems(["Kapali", "Kick flasi", "Nota rengi", "VU parlakligi"])
        self.c_kbd.setToolTip("ASUS TUF klavye isigi muzige tepki versin (renk kaydedilmez)")
        self.c_kbd.currentIndexChanged.connect(self.kbd_mode)
        tb.addWidget(self.c_kbd)
        self.kbd_t = QtCore.QElapsedTimer(); self.kbd_t.start(); self.kbd_lvl = 0.0
        self.bg_last = -1
        add = QtWidgets.QPushButton("+ PANEL"); add.setObjectName("ghost")
        add.setToolTip("Kapatilan bir paneli geri ac"); add.clicked.connect(self.add_panel)
        tb.addWidget(add)
        rst = QtWidgets.QPushButton("SIFIRLA"); rst.setToolTip("Yerlesimi sifirla"); rst.clicked.connect(self.reset_layout)
        tb.addWidget(rst)
        self.fps = QtWidgets.QLabel(""); self.fps.setObjectName("muted"); tb.addWidget(self.fps)
        self.c_big.currentIndexChanged.connect(self.reconf)
        self.c_fast.currentIndexChanged.connect(self.reconf)
        self.c_decay.currentIndexChanged.connect(
            lambda i: setattr(self.an, "decay", [0.0, 0.80, 0.90, 0.96][i]))

        # 3 satir x 2 sutun, surukle-birak boyutlanabilir
        defaults = [[ScopeView, WideChromaView], [SpectrumView, MelodyView], [RhythmView, VUMeterView]]
        self.vs = QtWidgets.QSplitter(QtCore.Qt.Vertical); self.vs.setHandleWidth(6)
        self.rows, self.panels = [], []
        for row in defaults:
            hs = QtWidgets.QSplitter(QtCore.Qt.Horizontal); hs.setHandleWidth(6)
            for v in row:
                pn = Panel(v); hs.addWidget(pn); self.panels.append(pn)
            self.vs.addWidget(hs); self.rows.append(hs)
        c = QtWidgets.QWidget(); c.setObjectName("root"); c.setAutoFillBackground(True)
        self.flash_pal = c.palette(); self.flash_pal.setColor(QtGui.QPalette.Window, QtGui.QColor(INK))
        c.setPalette(self.flash_pal)
        l = QtWidgets.QVBoxLayout(c); l.setContentsMargins(6, 6, 6, 6)
        l.addWidget(self.vs); self.setCentralWidget(c)
        self.glow = EdgeGlow(c)
        QtCore.QTimer.singleShot(0, self.reset_layout)

        # Windows'ta normal QTimer ~15.6 ms'ye yuvarlanir -> 15 ms istek ~30 FPS'e duser
        self.t = QtCore.QTimer(); self.t.setTimerType(QtCore.Qt.PreciseTimer)
        self.t.timeout.connect(self.tick); self.t.start(14)
        self.clock = QtCore.QElapsedTimer(); self.clock.start(); self.frames = 0

    def set_theme(self, name):
        apply_theme(name)
        QtWidgets.QApplication.instance().setStyleSheet(build_qss())
        self.brand.setText("FALCON<span style='color:%s'>//</span>AUDIO" % RED)
        pal = self.flash_pal; pal.setColor(QtGui.QPalette.Window, QtGui.QColor(INK))
        self.centralWidget().setPalette(pal)
        retro = {"Retro Analog": ["CRT Osiloskop", "Analog VU (ibreli)", "LED Spektrum (31 bant)", "Melodi Izi",
                                  "Ritim (Bas/Davul)", "VU Metre"]}.get(name)
        for i, pn in enumerate(self.panels):       # renkler kurulumda okunur -> gorunumleri yeniden kur
            want = retro[i] if retro and i < len(retro) else None
            if want and pn.combo.currentText() != want:
                pn.combo.setCurrentText(want)      # set_view'i combo sinyali cagirir
            else:
                pn.set_view(pn.combo.currentIndex())
        self.glow.update()

    def kbd_mode(self, i):
        if i == 0 and kbd.ok:                      # kapatinca tema rengine sabitle
            kbd.set(rgb(RED))
        elif i and not kbd.open():
            self.c_kbd.setCurrentIndex(0)
            self.c_kbd.setToolTip("Bu bilgisayarda ASUS klavye RGB erisimi yok")

    def kbd_tick(self, A):
        mode = self.c_kbd.currentIndex()
        if mode == 0 or self.kbd_t.elapsed() < 25:  # en fazla ~40 guncelleme/sn
            return
        self.kbd_t.restart()
        if mode == 1:                               # kick flasi: sonuk tema rengi -> beyaz
            f = A["bass_flash"]
            c = mix("#000000", RED, 0.25) if f < 0.05 else mix(RED_BRIGHT, "#ffffff", 0.6 * f)
            if f >= 0.05:
                c = tuple(int(v * (0.25 + 0.75 * f)) for v in c)
        elif mode == 2:                             # nota rengi: renk cemberi, guc = parlaklik
            ch = A["chroma"]; k = int(np.argmax(ch)); s = float(ch[k])
            q = QtGui.QColor.fromHsvF(k / 12, 1.0, min(1.0, 0.15 + 0.85 * s))
            c = (q.red(), q.green(), q.blue())
        else:                                       # VU: ses seviyesi -> tema renginde parlaklik
            x = (A["L"][-2048:] + A["R"][-2048:]) * 0.5
            d = 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)
            lv = float(np.clip((d + 40) / 34, 0, 1))
            self.kbd_lvl = lv if lv > self.kbd_lvl else self.kbd_lvl * 0.85 + lv * 0.15
            c = tuple(int(v * self.kbd_lvl) for v in rgb(RED_BRIGHT))
        kbd.set(c)

    def apply_flash(self, a):
        """Kick'te ana pencerenin kenar ve koselerinde beyaz parlama."""
        if not self.b_flash.isChecked():
            a = 0.0
        q = int(round(a * 20))                    # 21 kademe: sadece degisince boya
        if q == self.bg_last:
            return
        self.bg_last = q
        self.glow.set_level(q / 20)

    def add_panel(self):
        for pn in self.panels:
            if pn.isHidden():
                pn.show(); pn.parent().show(); return

    def reset_layout(self):
        for pn in self.panels:
            pn.show()
        for r in self.rows:
            r.show()
        H, W = self.vs.height(), self.vs.width()
        self.vs.setSizes([int(H * .28), int(H * .40), int(H * .32)])
        for r, f in zip(self.rows, (.62, .44, .62)):      # satir basina sol panel orani
            r.setSizes([int(W * f), int(W * (1 - f))])

    def set_wf(self, s):
        WaterfallView.seconds = s
        for pn in self.panels:
            if isinstance(pn.view, WaterfallView):
                pn.view.set_seconds(s)

    def pick_device(self):
        dev = choose_device(self)
        if dev is None:
            return
        open_stream(dev)
        self.dev_lbl.setText(dev["name"].replace(" [Loopback]", "")[:40])
        self.reconf()
        for pn in self.panels:          # RATE degismis olabilir -> gorunumleri yenile
            pn.set_view(pn.combo.currentIndex())

    def reconf(self):
        big = int(self.c_big.currentText())
        fast = [1024, 2048, 4096, 8192][self.c_fast.currentIndex()]
        d = self.an.decay
        self.an.configure(big, fast); self.an.decay = d

    def tick(self):
        A = self.an.run()
        if A is None:
            return
        self.apply_flash(A["bass_flash"] * self.s_flash.value() / 100)
        self.kbd_tick(A)
        for r in self.rows:                       # bos kalan satiri gizle
            r.setVisible(any(not r.widget(i).isHidden() for i in range(r.count())))
        for pn in self.panels:
            if pn.isHidden():                     # kapali panel cizilmez -> FPS kazanci
                continue
            try:
                pn.view.update(A)
            except Exception as e:
                print(pn.view.name, "hata:", e)
        self.frames += 1
        if self.clock.elapsed() > 1000:
            lat = self.an.FAST / RATE * 1000
            self.fps.setText(f"{self.frames} FPS · nota gecikmesi ~{lat:.0f} ms")
            self.frames = 0; self.clock.restart()

def choose_device(parent=None):
    devs = list_devices()
    dlg = QtWidgets.QDialog(parent); dlg.setWindowTitle("FALCON // Ses kaynagi sec")
    dlg.resize(620, 380)
    v = QtWidgets.QVBoxLayout(dlg)
    t = QtWidgets.QLabel("SES KAYNAGI SEC"); t.setObjectName("brand"); v.addWidget(t)
    h = QtWidgets.QLabel("🔊 = bilgisayarda calan ses (Spotify vb.)   🎤 = mikrofon / hat girisi")
    h.setObjectName("muted"); v.addWidget(h)
    lst = QtWidgets.QListWidget()
    lst.setStyleSheet(f"QListWidget{{background:{PANEL};border:1px solid {LINE};}}"
                      f"QListWidget::item{{padding:7px;}}"
                      f"QListWidget::item:selected{{background:{RED};color:{FG};}}")
    for label, _ in devs:
        lst.addItem(label)
    lst.setCurrentRow(0); v.addWidget(lst, 1)
    ok = QtWidgets.QPushButton("BASLAT"); v.addWidget(ok)
    ok.clicked.connect(dlg.accept); lst.itemDoubleClicked.connect(dlg.accept)
    if not devs or dlg.exec_() != QtWidgets.QDialog.Accepted:
        return None
    return devs[lst.currentRow()][1]

app = QtWidgets.QApplication([])
app.setStyleSheet(QSS)
import os
AUTOTEST = os.environ.get("SCOPE_AUTOTEST")          # test: dialogsuz baslat, 5 sn sonra kapan
first = list_devices()[0][1] if AUTOTEST else choose_device()
if AUTOTEST:
    QtCore.QTimer.singleShot(5000, app.quit)
if first is None:
    raise SystemExit
open_stream(first)
m = Main(); m.dev_lbl.setText(first["name"].replace(" [Loopback]", "")[:40]); m.show()
app.exec_()
stream.stop_stream(); stream.close(); p.terminate()
