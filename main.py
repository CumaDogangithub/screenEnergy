import cv2
import dlib
import numpy as np
import tkinter as tk
import math
import ctypes
import platform
import os
import glob
from screeninfo import get_monitors

# --- PLATFORM TESPİTİ ---
PLATFORM = platform.system()  # 'Windows', 'Linux', 'Darwin'

# --- PLATFORM'A ÖZEL İMPORTLAR ---
if PLATFORM == 'Windows':
    try:
        import win32gui
        import win32con
    except ImportError:
        print("Hata: pywin32 kurulu değil. Kurmak için: pip install pywin32")
        win32gui = None
        win32con = None

XLIB_AVAILABLE = False
if PLATFORM == 'Linux':
    # DISPLAY ayarlı değilse mevcut X11 soketlerinden otomatik bul (Wayland + XWayland)
    if not os.environ.get('DISPLAY'):
        sockets = sorted(glob.glob('/tmp/.X11-unix/X*'))
        for sock in sockets:
            num = sock.replace('/tmp/.X11-unix/X', '')
            os.environ['DISPLAY'] = f':{num}'
            break

    try:
        from Xlib import display as xdisplay, X
        from Xlib.ext import shape as xshape
        _xlib_display = xdisplay.Display()
        XLIB_AVAILABLE = True
    except ImportError:
        print("Uyarı: python-xlib kurulu değil. Pencere tespiti devre dışı.")
    except Exception:
        sockets = sorted(glob.glob('/tmp/.X11-unix/X*'))
        for sock in sockets:
            num = sock.replace('/tmp/.X11-unix/X', '')
            os.environ['DISPLAY'] = f':{num}'
            try:
                from Xlib import display as xdisplay, X
                from Xlib.ext import shape as xshape
                _xlib_display = xdisplay.Display()
                XLIB_AVAILABLE = True
                break
            except Exception:
                continue
        if not XLIB_AVAILABLE:
            print("Uyarı: Xlib display bulunamadı. Pencere tespiti devre dışı.")

# --- WINDOWS DPI ÖLÇEKLENDİRME HATASINI ÇÖZ ---
if PLATFORM == 'Windows':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# --- MONİTÖR TESPİTİ VE DİZİLİMİ ---
ham_ekranlar = get_monitors()
ekranlar = sorted(ham_ekranlar, key=lambda m: m.x)
toplam_ekran = len(ekranlar)

min_x_tumu = min(m.x for m in ekranlar)
min_y_tumu = min(m.y for m in ekranlar)
max_x_tumu = max(m.x + m.width for m in ekranlar)
max_y_tumu = max(m.y + m.height for m in ekranlar)
toplam_genislik = max_x_tumu - min_x_tumu
toplam_yukseklik = max_y_tumu - min_y_tumu

# --- TKINTER ROOT (gizli ana pencere) ---
root = tk.Tk()
root.overrideredirect(True)
root.geometry("1x1+-100+-100")
root.attributes('-alpha', 0.0)
root.wm_title("__se_overlay__")

# --- ACİL ÇIKIŞ ---
running = True
def quit_app(event=None):
    global running
    running = False

root.bind('<Escape>', quit_app)
root.bind('<q>', quit_app)
root.bind('<Q>', quit_app)

# --- CLICK-THROUGH (pencere başına) ---
def _apply_click_through(win):
    """Verilen tkinter penceresini tıklamalara şeffaf yapar."""
    if PLATFORM == 'Windows' and win32gui:
        try:
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            if hwnd == 0:
                hwnd = win.winfo_id()
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                                   ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
        except Exception:
            pass
    elif PLATFORM == 'Linux' and XLIB_AVAILABLE:
        try:
            wid = win.winfo_id()
            xwin = _xlib_display.create_resource_object('window', wid)
            # ShapeInput boş = tıklamalar geçer; ShapeBounding'e dokunmuyoruz
            xwin.shape_combine_rectangles(0, 2, 0, 0, [])
            _xlib_display.sync()
        except Exception:
            pass

# --- 4 STRIP + CURSOR PENCERELERİ ---
# Tek büyük overlay + delik yerine: focused alanın ETRAFINA 4 ayrı karartma şeridi
_STRIP_ALPHA = 0.75

_strips = {}
_strip_canvas = {}
for _n in ('top', 'bottom', 'left', 'right'):
    _w = tk.Toplevel(root)
    _w.overrideredirect(True)
    _w.attributes('-topmost', True)
    _w.attributes('-alpha', _STRIP_ALPHA)
    _w.wm_title("__se_overlay__")
    _w.geometry("1x1+-200+-200")
    _c = tk.Canvas(_w, bg='#111111', highlightthickness=0)
    _c.pack(fill=tk.BOTH, expand=True)
    _w.withdraw()
    _strips[_n] = _w
    _strip_canvas[_n] = _c

# Gaze imleci için küçük pencere
_cursor_win = tk.Toplevel(root)
_cursor_win.overrideredirect(True)
_cursor_win.wm_title("__se_overlay__")
_cursor_win.attributes('-topmost', True)
if PLATFORM == 'Windows':
    _cursor_win.attributes('-transparentcolor', 'black')
    _cursor_win.configure(bg='black')
else:
    _cursor_win.attributes('-alpha', 0.85)
    _cursor_win.configure(bg='#111111')
_cursor_canvas = tk.Canvas(_cursor_win, bg=_cursor_win.cget('bg'), highlightthickness=0, width=70, height=70)
_cursor_canvas.pack()
_cursor_win.withdraw()

# --- KALİBRASYON HEDEF NOKTASİ (köşe göstergesi) ---
_CAL_SIZE = 80
_cal_win = tk.Toplevel(root)
_cal_win.overrideredirect(True)
_cal_win.wm_title("__se_overlay__")
_cal_win.attributes('-topmost', True)
_cal_canvas = tk.Canvas(_cal_win, width=_CAL_SIZE, height=_CAL_SIZE,
                         bg='#000000', highlightthickness=0)
_cal_canvas.pack()
_cal_win.withdraw()

def _show_cal_target(step):
    """Kalibrasyon adımı için ekran köşesinde turuncu hedef noktası göster."""
    ekran_adi, kose = step
    idx = int(ekran_adi.replace("EKRAN_", "")) - 1
    ekran = ekranlar[idx]
    m = 4  # kenar boşluğu
    if kose == "SOL UST":
        tx, ty = ekran.x + m, ekran.y + m
    elif kose == "SAG UST":
        tx, ty = ekran.x + ekran.width - _CAL_SIZE - m, ekran.y + m
    elif kose == "SAG ALT":
        tx, ty = ekran.x + ekran.width - _CAL_SIZE - m, ekran.y + ekran.height - _CAL_SIZE - m
    else:  # SOL ALT
        tx, ty = ekran.x + m, ekran.y + ekran.height - _CAL_SIZE - m
    _cal_canvas.delete("all")
    _cal_canvas.create_oval(4, 4, _CAL_SIZE - 4, _CAL_SIZE - 4,
                             fill='#FF6600', outline='white', width=3)
    _cal_canvas.create_line(_CAL_SIZE // 2, 10, _CAL_SIZE // 2, _CAL_SIZE - 10,
                             fill='white', width=2)
    _cal_canvas.create_line(10, _CAL_SIZE // 2, _CAL_SIZE - 10, _CAL_SIZE // 2,
                             fill='white', width=2)
    _cal_win.geometry(f"{_CAL_SIZE}x{_CAL_SIZE}+{int(tx)}+{int(ty)}")
    _cal_win.deiconify()

import subprocess as _subprocess
import threading as _threading

# --- KWin SCRIPTING (KDE Plasma Wayland pencere tespiti) ---
_KWIN_SCRIPT = r"""
var SE_TIMER = new QTimer();
SE_TIMER.interval = 150;
SE_TIMER.timeout.connect(function() {
    var wins = workspace.stackingOrder;
    var result = [];
    for (var i = 0; i < wins.length; i++) {
        var c = wins[i];
        if (c.managed === false) continue;
        if (c.minimized) continue;
        var g = c.frameGeometry;
        if (g.width < 100 || g.height < 80) continue;
        var title = c.caption;
        if (title.indexOf("Odak Asistani") !== -1) continue;
        if (title.indexOf("__se_overlay__") !== -1) continue;
        if (title === "" || title === "Toplevel") continue;
        result.push("SE_WIN:" + title + "|" + Math.round(g.x) + "|" + Math.round(g.y) + "|" + Math.round(g.width) + "|" + Math.round(g.height));
    }
    if (result.length > 0)
        print("SE_LIST:" + result.join("||"));
});
SE_TIMER.start();
"""

_kwin_windows = []   # [(x1,y1,x2,y2), ...] — stacking order (son = en üstte)
_kwin_lock = _threading.Lock()
_kwin_proc = None
KWIN_AVAILABLE = False

def _start_kwin_scripting():
    global KWIN_AVAILABLE, _kwin_proc
    if PLATFORM != 'Linux':
        return
    try:
        script_path = '/tmp/screenEnergy_wins.js'
        with open(script_path, 'w') as f:
            f.write(_KWIN_SCRIPT)

        # Script'i yükle
        r = _subprocess.run(
            ['gdbus', 'call', '--session',
             '--dest', 'org.kde.KWin', '--object-path', '/Scripting',
             '--method', 'org.kde.kwin.Scripting.loadScript',
             script_path, 'screenEnergy'],
            capture_output=True, text=True, timeout=3
        )
        # Script ID'yi parse et: "(2,)" gibi
        import re
        m = re.search(r'\((\d+),\)', r.stdout)
        if not m:
            return
        script_id = m.group(1)

        # Script'i çalıştır
        _subprocess.run(
            ['gdbus', 'call', '--session',
             '--dest', 'org.kde.KWin',
             '--object-path', f'/Scripting/Script{script_id}',
             '--method', 'org.kde.kwin.Script.run'],
            timeout=3
        )

        # Journald'ı arka planda oku
        _kwin_proc = _subprocess.Popen(
            ['journalctl', '--user', '-f', '--output=cat', '--no-pager'],
            stdout=_subprocess.PIPE, text=True, stderr=_subprocess.DEVNULL
        )
        t = _threading.Thread(target=_kwin_journal_reader, daemon=True)
        t.start()
        KWIN_AVAILABLE = True
        print("KWin pencere tespiti aktif.")
    except Exception as e:
        print(f"KWin scripting başlatılamadı: {e}")

def _kwin_journal_reader():
    """Arka planda journald'dan KWin pencere verisi okur."""
    for line in _kwin_proc.stdout:
        if 'SE_LIST:' not in line:
            continue
        try:
            data = line.split('SE_LIST:', 1)[1].strip()
            wins = []
            for entry in data.split('||'):
                if not entry.startswith('SE_WIN:'):
                    continue
                fields = entry[7:].split('|')
                if len(fields) < 5:
                    continue
                title = fields[0]
                x, y, w, h = int(fields[1]), int(fields[2]), int(fields[3]), int(fields[4])
                if w > 50 and h > 50:
                    wins.append((x, y, x + w, y + h))
            with _kwin_lock:
                _kwin_windows[:] = wins
        except Exception:
            continue

def _kwin_window_at(x, y):
    """KWin cache'inden en üstteki pencereyi döndürür."""
    with _kwin_lock:
        result = None
        for (wx, wy, wr, wb) in _kwin_windows:
            if wx <= x <= wr and wy <= y <= wb:
                result = (wx, wy, wr, wb)  # Son eşleşme = en üstte
        return result

# --- UYGULAMA (PENCERE) BULUCU ---
def get_window_rect_under_gaze(x, y):
    if PLATFORM == 'Windows' and win32gui:
        try:
            hwnd = win32gui.WindowFromPoint((int(x), int(y)))
            hwnd_root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
            if hwnd_root == 0:
                hwnd_root = hwnd
            return win32gui.GetWindowRect(hwnd_root)
        except Exception:
            return None
    elif PLATFORM == 'Linux':
        # KWin (Wayland) → Xlib (XWayland) sıralamasıyla dene
        if KWIN_AVAILABLE:
            result = _kwin_window_at(int(x), int(y))
            if result:
                return result
        if XLIB_AVAILABLE:
            return _xlib_window_at(int(x), int(y))
    return None

def _xlib_window_at(x, y):
    try:
        screen = _xlib_display.screen()
        root_win = screen.root
        atom = _xlib_display.intern_atom('_NET_CLIENT_LIST')
        prop = root_win.get_full_property(atom, X.AnyPropertyType)
        if not prop:
            return None
        result = None
        result_area = float('inf')
        for wid in prop.value:
            try:
                win = _xlib_display.create_resource_object('window', wid)
                geom = win.get_geometry()
                trans = root_win.translate_coords(win, 0, 0)
                wx, wy = trans.x, trans.y
                ww, wh = geom.width, geom.height
                frame_atom = _xlib_display.intern_atom('_NET_FRAME_EXTENTS')
                frame_prop = win.get_full_property(frame_atom, X.AnyPropertyType)
                if frame_prop and len(frame_prop.value) >= 4:
                    fl, fr, ft, fb = frame_prop.value[:4]
                    wx -= fl; wy -= ft; ww += fl + fr; wh += ft + fb
                if wx <= x <= wx + ww and wy <= y <= wy + wh:
                    area = ww * wh
                    if area < result_area:
                        result = (wx, wy, wx + ww, wy + wh)
                        result_area = area
            except Exception:
                continue
        return result
    except Exception:
        return None

# --- KALİBRASYON VERİLERİ ---
kalibrasyon_adimlari = []
for i in range(toplam_ekran):
    kalibrasyon_adimlari.extend([
        (f"EKRAN_{i+1}", "SOL UST"), (f"EKRAN_{i+1}", "SAG UST"),
        (f"EKRAN_{i+1}", "SAG ALT"), (f"EKRAN_{i+1}", "SOL ALT")
    ])

kalibrasyon_verileri = {f"EKRAN_{i+1}": [] for i in range(toplam_ekran)}
adim_indeksi = 0
ekran_sinirlari = {}

def haritalari_hesapla():
    for i, ekran in enumerate(ekranlar):
        ekran_adi = f"EKRAN_{i+1}"
        koseler = kalibrasyon_verileri[ekran_adi]
        if len(koseler) == 4:
            ekran_sinirlari[ekran_adi] = {
                "goz_x_range": [min(k[0] for k in koseler), max(k[0] for k in koseler)],
                "goz_y_range": [min(k[1] for k in koseler), max(k[1] for k in koseler)],
                "ekran_x_range": [ekran.x, ekran.x + ekran.width],
                "ekran_y_range": [ekran.y, ekran.y + ekran.height],
                "merkez_goz": (sum(k[0] for k in koseler) / 4, sum(k[1] for k in koseler) / 4)
            }
    pass  # Overlay pencereleri draw_overlay içinde yönetiliyor

def bakilan_ekrani_bul(g_x, g_y):
    if adim_indeksi < len(kalibrasyon_adimlari):
        return None
    min_mesafe = float('inf')
    bulunan_ekran = None
    for ekran_adi, sinirlar in ekran_sinirlari.items():
        m_x, m_y = sinirlar["merkez_goz"]
        mesafe = math.hypot(g_x - m_x, g_y - m_y)
        if mesafe < min_mesafe:
            min_mesafe = mesafe
            bulunan_ekran = ekran_adi
    return bulunan_ekran

def draw_overlay(app_rect, guncel_sx, guncel_sy):
    """
    4 strip penceresiyle focused alanın ETRAFINI karartır.
    Focused alanın üzerinde hiç pencere olmaz → her zaman görünür.
    """
    if app_rect is None:
        for w in _strips.values():
            w.withdraw()
        _cursor_win.withdraw()
        return

    ax, ay, ar, ab = app_rect  # ekran koordinatları

    # Strip geometrileri: (genislik, yukseklik, ekran_x, ekran_y)
    configs = {
        'top':    (toplam_genislik, max(ay - min_y_tumu, 0),
                   min_x_tumu, min_y_tumu),
        'bottom': (toplam_genislik, max(toplam_yukseklik - (ab - min_y_tumu), 0),
                   min_x_tumu, ab),
        'left':   (max(ax - min_x_tumu, 0), ab - ay,
                   min_x_tumu, ay),
        'right':  (max(toplam_genislik - (ar - min_x_tumu), 0), ab - ay,
                   ar, ay),
    }
    # Yeşil çizgi: focused alana bakan kenar
    border = {
        'top':    lambda c, w, h: c.create_line(0, h - 2, w, h - 2, fill='lime', width=4),
        'bottom': lambda c, w, h: c.create_line(0, 2,     w, 2,     fill='lime', width=4),
        'left':   lambda c, w, h: c.create_line(w - 2, 0, w - 2, h, fill='lime', width=4),
        'right':  lambda c, w, h: c.create_line(2, 0,     2, h,     fill='lime', width=4),
    }

    for name, (sw, sh, sx, sy) in configs.items():
        win = _strips[name]
        cvs = _strip_canvas[name]
        if sw <= 0 or sh <= 0:
            win.withdraw()
            continue
        win.geometry(f"{int(sw)}x{int(sh)}+{int(sx)}+{int(sy)}")
        win.deiconify()
        cvs.configure(width=int(sw), height=int(sh))
        cvs.delete("all")
        border[name](cvs, int(sw), int(sh))
        if not hasattr(win, '_ct'):
            win.update()
            _apply_click_through(win)
            win._ct = True

    # Gaze imleci (focused alan içinde göster)
    _cursor_canvas.delete("all")
    _cursor_canvas.create_oval(5, 5, 65, 65, outline='red', width=4)
    _cursor_win.geometry(f"70x70+{int(guncel_sx) - 35}+{int(guncel_sy) - 35}")
    _cursor_win.deiconify()
    if not hasattr(_cursor_win, '_ct'):
        _cursor_win.update()
        _apply_click_through(_cursor_win)
        _cursor_win._ct = True

# --- DLIB YÜKLEME ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, 'shape_predictor_68_face_landmarks.dat')

if not os.path.exists(MODEL_PATH):
    print(f"Hata: dlib model dosyası bulunamadı: {MODEL_PATH}")
    print("Lütfen aşağıdaki komutu çalıştırın:")
    print("  wget http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2")
    print("  bzip2 -d shape_predictor_68_face_landmarks.dat.bz2")
    exit(1)

face_detector = dlib.get_frontal_face_detector()
landmark_predictor = dlib.shape_predictor(MODEL_PATH)

# KWin scripting'i başlat (KDE Plasma Wayland için pencere tespiti)
_start_kwin_scripting()

# Sol göz landmark indeksleri (dlib 68-nokta modeli)
LEFT_EYE_IDX = list(range(36, 42))

def get_eye_center(landmarks, eye_indices):
    """Göz landmarklarının merkezini döndürür (iris tahmini)."""
    pts = [(landmarks.part(i).x, landmarks.part(i).y) for i in eye_indices]
    cx = sum(p[0] for p in pts) // len(pts)
    cy = sum(p[1] for p in pts) // len(pts)
    return cx, cy

# İlk kalibrasyon hedefini göster
if kalibrasyon_adimlari:
    _show_cal_target(kalibrasyon_adimlari[0])
    root.update()

# --- KAMERA ---
cap = cv2.VideoCapture(0)
prev_sx, prev_sy = 0, 0
alpha = 0.1

while cap.isOpened() and running:
    success, frame = cap.read()
    if not success:
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    faces = face_detector(gray, 0)

    goz_x, goz_y = 0, 0

    for face in faces:
        landmarks = landmark_predictor(gray, face)
        goz_x, goz_y = get_eye_center(landmarks, LEFT_EYE_IDX)
        cv2.circle(frame, (goz_x, goz_y), 5, (0, 255, 255), -1)
        break  # Sadece ilk yüz

    if adim_indeksi == len(kalibrasyon_adimlari):
        bakilan_ekran = bakilan_ekrani_bul(goz_x, goz_y)

        if bakilan_ekran:
            snr = ekran_sinirlari[bakilan_ekran]

            hedef_sx = np.interp(goz_x, snr["goz_x_range"], snr["ekran_x_range"])
            hedef_sy = np.interp(goz_y, snr["goz_y_range"], snr["ekran_y_range"])

            if prev_sx == 0:
                prev_sx, prev_sy = hedef_sx, hedef_sy
            guncel_sx = int(alpha * hedef_sx + (1 - alpha) * prev_sx)
            guncel_sy = int(alpha * hedef_sy + (1 - alpha) * prev_sy)
            prev_sx, prev_sy = guncel_sx, guncel_sy

            app_rect = get_window_rect_under_gaze(guncel_sx, guncel_sy)
            draw_overlay(app_rect, guncel_sx, guncel_sy)

    try:
        root.update()
    except tk.TclError:
        pass

    cv2.putText(frame, f"Goz: X:{goz_x} Y:{goz_y}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    if adim_indeksi < len(kalibrasyon_adimlari):
        hedef_ekran, hedef_kose = kalibrasyon_adimlari[adim_indeksi]
        cv2.putText(frame, f"LUTFEN {hedef_ekran} - {hedef_kose} KOSESINE BAK", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(frame, "KAYDETMEK ICIN 'BOSLUK' TUSUNA BAS", (10, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    else:
        cv2.putText(frame, "DURUM: ODAK ASISTANI AKTIF", (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    cv2.imshow('Odak Asistani - Tam Surum', frame)

    key = cv2.waitKey(5) & 0xFF
    if key == 27 or key == ord('q') or key == ord('Q'):  # ESC veya q
        break
    elif key == 32 and adim_indeksi < len(kalibrasyon_adimlari):
        hedef_ekran, hedef_kose = kalibrasyon_adimlari[adim_indeksi]
        kalibrasyon_verileri[hedef_ekran].append((goz_x, goz_y))
        print(f"Kaydedildi: {hedef_ekran} - {hedef_kose}  goz=({goz_x},{goz_y})")
        adim_indeksi += 1
        if adim_indeksi == len(kalibrasyon_adimlari):
            haritalari_hesapla()
            _cal_win.withdraw()
            cv2.moveWindow('Odak Asistani - Tam Surum', 10, 10)
            cv2.resizeWindow('Odak Asistani - Tam Surum', 320, 240)
            print("\nKALIBRASYON TAMAM! Odak asistani aktif.")
        else:
            _show_cal_target(kalibrasyon_adimlari[adim_indeksi])

cap.release()
cv2.destroyAllWindows()
if _kwin_proc:
    _kwin_proc.terminate()
root.destroy()
