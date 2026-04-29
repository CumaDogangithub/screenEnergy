import cv2
import mediapipe as mp
import numpy as np
import tkinter as tk
import math
import json
import os
import win32api
import win32con
import win32gui
import ctypes
from collections import deque
from screeninfo import get_monitors

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    pass

# --- MONİTÖR TESPİTİ ---
ham_ekranlar = get_monitors()
ekranlar     = sorted(ham_ekranlar, key=lambda m: m.x)
toplam_ekran = len(ekranlar)

# -----------------------------------------------------------------------
# TKINTER PENCERELERİ
# -----------------------------------------------------------------------
root = tk.Tk()
root.withdraw()

# Kalibrasyon noktası
DOT_R = 20
SIZE  = DOT_R * 2 + 8
kal_dot = tk.Toplevel(root)
kal_dot.overrideredirect(True)
kal_dot.attributes('-topmost', True)
kal_dot.attributes('-transparentcolor', 'white')
kal_cv = tk.Canvas(kal_dot, width=SIZE, height=SIZE, bg='white', highlightthickness=0)
kal_cv.pack()
kal_cv.create_oval(4, 4, SIZE-4, SIZE-4, fill='red', outline='yellow', width=3)
kal_cv.create_oval(SIZE//2-4, SIZE//2-4, SIZE//2+4, SIZE//2+4, fill='white', outline='white')
kal_cv.create_line(SIZE//2, 2, SIZE//2, SIZE-2, fill='yellow', width=1)
kal_cv.create_line(2, SIZE//2, SIZE-2, SIZE//2, fill='yellow', width=1)
kal_dot.withdraw()

# Bakış imleci (sistem faresi hareket ETMEZ, bu ayrı penceredir)
GCS = 64
gaz_cur = tk.Toplevel(root)
gaz_cur.overrideredirect(True)
gaz_cur.attributes('-topmost', True)
gaz_cur.attributes('-transparentcolor', 'black')
gaz_cv = tk.Canvas(gaz_cur, width=GCS, height=GCS, bg='black', highlightthickness=0)
gaz_cv.pack()
_gr   = gaz_cv.create_oval(4, 4, GCS-4, GCS-4, outline='cyan', width=3)
_glv  = gaz_cv.create_line(GCS//2, 4,   GCS//2, GCS-4, fill='cyan', width=1)
_glh  = gaz_cv.create_line(4, GCS//2,   GCS-4,  GCS//2, fill='cyan', width=1)
_gdot = gaz_cv.create_oval(GCS//2-5, GCS//2-5, GCS//2+5, GCS//2+5, fill='cyan', outline='')
gaz_cur.withdraw()

gaz_cur.update()
_gaz_hwnd = win32gui.GetParent(gaz_cur.winfo_id())
if _gaz_hwnd == 0:
    _gaz_hwnd = gaz_cur.winfo_id()
_gex = win32gui.GetWindowLong(_gaz_hwnd, win32con.GWL_EXSTYLE)
win32gui.SetWindowLong(_gaz_hwnd, win32con.GWL_EXSTYLE,
                       _gex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

_gaz_visible  = False
_gaz_flash_cd = 0

def _gaz_renk(color):
    gaz_cv.itemconfig(_gr,   outline=color)
    gaz_cv.itemconfig(_glv,  fill=color)
    gaz_cv.itemconfig(_glh,  fill=color)
    gaz_cv.itemconfig(_gdot, fill=color)

def _gaz_flash(color, frames=14):
    global _gaz_flash_cd
    _gaz_renk(color)
    _gaz_flash_cd = frames

# -----------------------------------------------------------------------
# BAKIŞ İMLECİ KONUMLU TIK (sistem faresi hareket etmez)
# -----------------------------------------------------------------------
# WS_EX_TRANSPARENT olduğundan WindowFromPoint bakış imlecini atlar
# ve altındaki pencereyi döndürür — doğrudan o pencereye PostMessage gönderir.
# -----------------------------------------------------------------------
def click_at_point(x, y, is_right=False):
    try:
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        if hwnd == 0 or not win32gui.IsWindowVisible(hwnd):
            return
        cx, cy = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
        lp = (cy & 0xFFFF) << 16 | (cx & 0xFFFF)
        if is_right:
            win32gui.PostMessage(hwnd, 0x0204, 0x0002, lp)  # WM_RBUTTONDOWN
            win32gui.PostMessage(hwnd, 0x0205, 0x0000, lp)  # WM_RBUTTONUP
        else:
            win32gui.PostMessage(hwnd, 0x0201, 0x0001, lp)  # WM_LBUTTONDOWN
            win32gui.PostMessage(hwnd, 0x0202, 0x0000, lp)  # WM_LBUTTONUP
    except Exception:
        pass

# -----------------------------------------------------------------------
# YÜZ KUTUSU + BAKIŞ VEKTÖRü
# -----------------------------------------------------------------------
ZONE_X = (0.08, 0.92)
ZONE_Y = (0.04, 0.96)

def bakis_vektoru_hesapla(lm, w, h):
    iris_x = (lm[468].x + lm[473].x) / 2.0 * w
    iris_y = (lm[468].y + lm[473].y) / 2.0 * h
    zx1 = ZONE_X[0]*w; zx2 = ZONE_X[1]*w
    zy1 = ZONE_Y[0]*h; zy2 = ZONE_Y[1]*h
    rx = float(np.clip((iris_x - zx1) / max(zx2-zx1, 1), 0.0, 1.0))
    ry = float(np.clip((iris_y - zy1) / max(zy2-zy1, 1), 0.0, 1.0))
    return rx, ry, iris_x, iris_y

def zone_ciz(frame, w, h, iris_x, iris_y, yuz_ok):
    zx1=int(ZONE_X[0]*w); zx2=int(ZONE_X[1]*w)
    zy1=int(ZONE_Y[0]*h); zy2=int(ZONE_Y[1]*h)
    oz_cx=(zx1+zx2)//2;   oz_cy=(zy1+zy2)//2
    if not yuz_ok:
        renk=(50,50,220); et="YUZ ALGILANAMADI!"
    else:
        rn=(iris_x-zx1)/max(zx2-zx1,1)
        tn=(iris_y-zy1)/max(zy2-zy1,1)
        if 0.04<=rn<=0.96 and 0.04<=tn<=0.96:
            renk=(0,210,0); et="KAFANI BU KUTUDA TUT"
        else:
            renk=(0,150,255); et="KAFANI MERKEZE AL!"
    cv2.rectangle(frame,(zx1,zy1),(zx2,zy2),renk,1)
    cl=24
    for cx,cy,dx,dy in [(zx1,zy1,1,1),(zx2,zy1,-1,1),(zx2,zy2,-1,-1),(zx1,zy2,1,-1)]:
        cv2.line(frame,(cx,cy),(cx+dx*cl,cy),renk,3)
        cv2.line(frame,(cx,cy),(cx,cy+dy*cl),renk,3)
    cv2.ellipse(frame,(oz_cx,oz_cy),((zx2-zx1)//3,int((zy2-zy1)*0.40)),0,0,360,(70,70,70),1)
    cv2.putText(frame,et,(zx1+4,zy1-6),cv2.FONT_HERSHEY_SIMPLEX,0.48,renk,1)
    if yuz_ok:
        ix,iy=int(iris_x),int(iris_y)
        cv2.circle(frame,(ix,iy), 7,(0,255,255),-1)
        cv2.circle(frame,(ix,iy),15,(0,200,200), 1)

# -----------------------------------------------------------------------
# GÖZ KIRPMA — EAR (Eye Aspect Ratio)
# -----------------------------------------------------------------------
# Flip sonrası MediaPipe kişinin perspektifinden etiket verir:
#   Kişinin SAĞ gözü → indeksler [362,385,387,263,373,380]
#   Kişinin SOL gözü → indeksler [33,160,158,133,153,144]
# Kullanıcı geri bildirimi: bu ikisi görünürde ters → sol/sağ click takas edildi.
#
# solo sayaç: yalnızca O göz kapalıyken (diğeri açıkken) artar.
# Doğal kırpma (her iki göz birden) → solo sayaç 0 kalır → tık olmaz.
# -----------------------------------------------------------------------
_IDX_SAG = [362, 385, 387, 263, 373, 380]  # kişinin sağ gözü → sağ tık
_IDX_SOL = [33,  160, 158, 133, 153, 144]  # kişinin sol gözü → sol tık
EAR_TRESH = 0.22
BLK_MIN   = 3
BLK_MAX   = 14

_sl_solo  = 0   # sol-solo kare sayacı
_sg_solo  = 0   # sağ-solo kare sayacı
_psl      = False
_psg      = False
_tik_cd   = 0
TIK_CD    = 22

def _ear(lm, idx):
    p = [(lm[i].x, lm[i].y) for i in idx]
    h = math.hypot(p[3][0]-p[0][0], p[3][1]-p[0][1])
    if h < 1e-5: return 0.3
    return (math.hypot(p[1][0]-p[5][0], p[1][1]-p[5][1]) +
            math.hypot(p[2][0]-p[4][0], p[2][1]-p[4][1])) / (2.0*h)

def blink_isle(lm):
    """Döndürür: None, 'sol_tik', 'sag_tik'."""
    global _sl_solo, _sg_solo, _psl, _psg, _tik_cd
    if _tik_cd > 0:
        _tik_cd -= 1
        return None

    sl_ear = _ear(lm, _IDX_SOL)
    sg_ear = _ear(lm, _IDX_SAG)
    sl_c   = sl_ear < EAR_TRESH
    sg_c   = sg_ear < EAR_TRESH

    action = None

    # Sol göz yalnız kapandı → sol tık
    if sl_c and not sg_c:
        _sl_solo += 1
    else:
        if _psl and not sl_c:
            if BLK_MIN <= _sl_solo <= BLK_MAX:
                action = 'sol_tik'
        if not sl_c:
            _sl_solo = 0

    # Sağ göz yalnız kapandı → sağ tık
    if sg_c and not sl_c:
        _sg_solo += 1
    else:
        if _psg and not sg_c:
            if BLK_MIN <= _sg_solo <= BLK_MAX and action is None:
                action = 'sag_tik'
        if not sg_c:
            _sg_solo = 0

    _psl = sl_c; _psg = sg_c
    if action:
        _tik_cd = TIK_CD
    return action

def ear_hud(frame, lm, w):
    sl = _ear(lm, _IDX_SOL); sg = _ear(lm, _IDX_SAG)
    cv2.putText(frame, f"SOL:{sl:.2f}", (w-140, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.48, (0,255,0) if sl>=EAR_TRESH else (0,0,255), 1)
    cv2.putText(frame, f"SAG:{sg:.2f}", (w-140, 50), cv2.FONT_HERSHEY_SIMPLEX,
                0.48, (0,255,0) if sg>=EAR_TRESH else (0,0,255), 1)

# -----------------------------------------------------------------------
# EL HAREKETLERİ  —  ÇIMDIK (İŞARET+BAŞPARMAK) TABANLI KONTROL
# -----------------------------------------------------------------------
# Çimdik = işaret ucu (8) + baş parmak ucu (4) birbirine yakın.
#
# Çimdik AÇIKKEN:
#   Yatay (dx):  sağa kayma → ses artır  |  sola → ses kıs
#   Dikey (dy):  parmak yukarı → scroll AŞAĞI (doğal dokunmatik yön)
#                parmak aşağı  → scroll YUKARI
#
# Yön kilidi: bir yöne scroll başlayınca parmağı geri getirince
#   ters scroll ateşlenmez; hız sıfıra düşünce kilit açılır.
# Çimdik bırakılınca tüm durum sıfırlanır.
# -----------------------------------------------------------------------
PINCH_THR_ON  = 0.038   # çimdik kapanma eşiği — parmaklar iyice değmeli
PINCH_THR_OFF = 0.058   # histerezis: çimdik açılma eşiği
PINCH_HIST    = deque(maxlen=12)
_pinch_active = False

VOL_IV   = 5     # ses adımları arası minimum kare (daha hızlı)
SCR_IV   = 3     # scroll adımları arası minimum kare (daha hızlı)
MOVE_THR = 0.013
SPAN     = 4
VK_VOLU  = 0xAF
VK_VOLD  = 0xAE

_vol_cd       = 0
_scr_cd       = 0
_scr_dir      = 0    # 0=boş, -1=aşağı-scroll aktif, +1=yukarı-scroll aktif
_scr_idle     = 0    # düşük hızda geçen kare sayısı
SCR_IDLE_FRAMES = 14  # bu kadar kare sonra yön kilidi açılır


def _vol(d):
    vk = VK_VOLU if d > 0 else VK_VOLD
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


def _scroll_at(d, gx, gy):
    """Bakış imleci konumundaki pencereye WM_MOUSEWHEEL gönderir."""
    try:
        hwnd = win32gui.WindowFromPoint((int(gx), int(gy)))
        if hwnd == 0 or not win32gui.IsWindowVisible(hwnd):
            return
        delta = 240 if d > 0 else -240   # 2× hız
        lp = (int(gy) & 0xFFFF) << 16 | (int(gx) & 0xFFFF)
        wp = (delta & 0xFFFF) << 16
        win32gui.PostMessage(hwnd, 0x020A, wp, lp)
    except Exception:
        pass


# -----------------------------------------------------------------------
# HOVER & ODAK TESPİTİ
# -----------------------------------------------------------------------
_INTERACTIVE_CLASSES = {
    'Chrome_RenderWidgetHostHWND', 'MozillaWindowClass',
    'MozillaCompositorWindowClass', 'EdgeHTML',
}
_HOVER_EXPAND = 14   # px: element sınırını bu kadar genişlet (genişletilmiş hitbox)

def hover_at_point(x, y):
    """
    Bakış imleci altındaki pencereye WM_MOUSEMOVE gönderir.
    Browser penceresindeyse True döner (CSS :hover tetiklenmiş olur).
    """
    try:
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        if hwnd == 0 or not win32gui.IsWindowVisible(hwnd):
            return False
        cx, cy = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
        lp = (cy & 0xFFFF) << 16 | (cx & 0xFFFF)
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        cls = win32gui.GetClassName(hwnd)
        return cls in _INTERACTIVE_CLASSES or 'render' in cls.lower()
    except Exception:
        return False


def thumb_hud(frame, hand_lm, w, h):
    """Kamerada baş+işaret parmak uçlarını ve çimdik durumunu göster."""
    t4 = hand_lm[4]; t8 = hand_lm[8]
    p4 = (int(t4.x*w), int(t4.y*h))
    p8 = (int(t8.x*w), int(t8.y*h))
    renk = (0, 255, 0) if _pinch_active else (255, 165, 0)
    cv2.circle(frame, p4, 10, renk, 2)
    cv2.circle(frame, p8,  8, renk, 2)
    cv2.line(frame, p4, p8, renk, 1)
    if _pinch_active:
        mx = (p4[0]+p8[0])//2; my = (p4[1]+p8[1])//2
        cv2.circle(frame, (mx, my), 14, (0, 255, 255), 2)


def hand_isle(hand_lm, gx=None, gy=None):
    """Çimdik tabanlı ses ve scroll kontrolü."""
    global _vol_cd, _scr_cd, _pinch_active, _scr_dir, _scr_idle

    t4   = hand_lm[4]
    t8   = hand_lm[8]
    dist = math.hypot(t4.x - t8.x, t4.y - t8.y)

    # Çimdik histerezisi
    if dist < PINCH_THR_ON:
        _pinch_active = True
    elif dist > PINCH_THR_OFF:
        _pinch_active = False
        PINCH_HIST.clear()
        _scr_dir = 0; _scr_idle = 0
        return []

    if not _pinch_active:
        return []

    # Çimdik merkezi takibi
    cx = (t4.x + t8.x) / 2.0
    cy = (t4.y + t8.y) / 2.0
    PINCH_HIST.append((cx, cy))

    labels = []
    if len(PINCH_HIST) <= SPAN:
        return labels

    pos = list(PINCH_HIST)
    dx  = pos[-1][0] - pos[-(SPAN+1)][0]
    dy  = pos[-1][1] - pos[-(SPAN+1)][1]

    # ── YATAY → SES ──────────────────────────────────────────────────────
    if _vol_cd > 0:
        _vol_cd -= 1
    elif abs(dx) > MOVE_THR:
        _vol(+1 if dx > 0 else -1)
        _vol_cd = VOL_IV
        labels.append('SES ↑' if dx > 0 else 'SES ↓')

    # ── DİKEY → SCROLL (doğal yön: parmak yukarı = içerik aşağı kayar) ──
    if abs(dy) < MOVE_THR * 0.35:
        _scr_idle += 1
        if _scr_idle >= SCR_IDLE_FRAMES:
            _scr_dir = 0          # yön kilidini aç
    else:
        _scr_idle = 0

    if _scr_cd > 0:
        _scr_cd -= 1
    elif abs(dy) > MOVE_THR and gx is not None:
        # dy < 0 → parmak yukarı → scroll DOWN (-1) | dy > 0 → parmak aşağı → scroll UP (+1)
        raw_dir = -1 if dy < 0 else 1
        if _scr_dir != 0 and raw_dir != _scr_dir:
            pass  # return-motion koruması: önceki yönün tersini engelle
        else:
            _scr_dir = raw_dir
            _scroll_at(raw_dir, gx, gy)
            _scr_cd = SCR_IV
            labels.append('SCROLL ↓' if raw_dir == -1 else 'SCROLL ↑')

    return labels

# -----------------------------------------------------------------------
# NAVİGASYON GESTURE  —  GERİ / İLERİ
# -----------------------------------------------------------------------
# Poz: el dikey + parmaklar birleşik ve dik + baş parmak yukarı
# → "primed" modu aktif
# Primed'dayken parmak uçları sola kayarsa → Alt+Sol (geri)
#                              sağa kayarsa → Alt+Sağ (ileri)
# -----------------------------------------------------------------------
_NAV_VERT_THR   = 0.12   # bileğe göre orta MCP'nin minimum yukarıda olma miktarı
_NAV_THUMB_THR  = 0.10   # baş parmak ucu, bileğin bu kadar üzerinde olmalı
_NAV_SPREAD_THR = 0.07   # 4 parmak ucu max x-spread (birleşiklik)
_NAV_BEND_THR   = 0.055  # primed'dan sonra tetikleyen x kayması
_nav_state      = 'idle' # 'idle' | 'primed'
_nav_prime_x    = None
_nav_cd         = 0
NAV_CD          = 50     # tetiklemeden sonra bekleme karesi


def _nav_poz_mu(lm):
    """El dikey, parmaklar birleşik ve dik, baş parmak yukarı → True."""
    # El dikey: bileğe göre orta MCP yeterince yukarıda
    if lm[0].y - lm[9].y < _NAV_VERT_THR:
        return False
    # Baş parmak yukarı: thumb tip bileğin üzerinde
    if lm[0].y - lm[4].y < _NAV_THUMB_THR:
        return False
    # Parmaklar birleşik: işaret-serçe uçları arasında dar x aralığı
    tips_x = [lm[i].x for i in [8, 12, 16, 20]]
    if max(tips_x) - min(tips_x) > _NAV_SPREAD_THR:
        return False
    # Parmaklar dik (bükülmemiş): her tip, kendi MCP'sinin üzerinde
    for tip, mcp in [(8, 5), (12, 9), (16, 13), (20, 17)]:
        if lm[tip].y >= lm[mcp].y:
            return False
    return True


def _send_back():
    win32api.keybd_event(0x12, 0, 0, 0)                         # Alt ↓
    win32api.keybd_event(0x25, 0, 0, 0)                         # Left ↓
    win32api.keybd_event(0x25, 0, win32con.KEYEVENTF_KEYUP, 0)  # Left ↑
    win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)  # Alt ↑


def _send_forward():
    win32api.keybd_event(0x12, 0, 0, 0)
    win32api.keybd_event(0x27, 0, 0, 0)                         # Right ↓
    win32api.keybd_event(0x27, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)


def nav_isle(lm):
    """Geri/ileri gesture durumunu günceller. Görüntülenecek etiket döner."""
    global _nav_state, _nav_cd, _nav_prime_x
    if _nav_cd > 0:
        _nav_cd -= 1
        return ''
    poz = _nav_poz_mu(lm)
    tip_cx = sum(lm[i].x for i in [8, 12, 16, 20]) / 4.0

    if _nav_state == 'idle':
        if poz:
            _nav_state = 'primed'
            _nav_prime_x = tip_cx
        return ''

    # primed durumu
    if not poz:
        _nav_state = 'idle'
        return ''
    dx = tip_cx - _nav_prime_x
    if dx < -_NAV_BEND_THR:
        _send_back()
        _nav_state = 'idle'; _nav_cd = NAV_CD
        return 'GERI ◀'
    if dx > _NAV_BEND_THR:
        _send_forward()
        _nav_state = 'idle'; _nav_cd = NAV_CD
        return 'ILERI ▶'
    return 'HAZIR ✊'


# -----------------------------------------------------------------------
# 9 NOKTA KALİBRASYON
# -----------------------------------------------------------------------
IZGARA           = [(fx,fy) for fy in [0.1,0.5,0.9] for fx in [0.1,0.5,0.9]]
FRAMES_PER_POINT = 30
WARMUP_FRAMES    = 20   # boşluk basıldıktan sonra toplama öncesi bekleme

kalibrasyon_adimlari = []
for _i, _ekr in enumerate(ekranlar):
    for _fx, _fy in IZGARA:
        kalibrasyon_adimlari.append({
            'ekran_adi': f"EKRAN_{_i+1}",
            'screen_x':  int(_ekr.x + _fx * _ekr.width),
            'screen_y':  int(_ekr.y + _fy * _ekr.height),
        })

ekran_verileri      = {f"EKRAN_{i+1}": {'goz':[], 'screen':[]} for i in range(toplam_ekran)}
homography_matrices = {}
ekran_merkezleri    = {}
adim_indeksi   = 0
toplama_aktif  = False
toplama_buffer = []
toplama_warmup = 0

def hedef_goster():
    if adim_indeksi >= len(kalibrasyon_adimlari):
        kal_dot.withdraw(); return
    a = kalibrasyon_adimlari[adim_indeksi]
    kal_dot.geometry(f"{SIZE}x{SIZE}+{a['screen_x']-SIZE//2}+{a['screen_y']-SIZE//2}")
    kal_dot.deiconify(); kal_dot.lift()

def haritalari_hesapla():
    for en, veri in ekran_verileri.items():
        if len(veri['goz']) < 4: continue
        src = np.array(veri['goz'],    dtype=np.float32)
        dst = np.array(veri['screen'], dtype=np.float32)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=50.0)
        if H is not None:
            homography_matrices[en] = H
            print(f"{en}: {int(mask.sum()) if mask is not None else len(src)}/{len(src)}")
        ekran_merkezleri[en] = (float(np.mean(src[:,0])), float(np.mean(src[:,1])))

# -----------------------------------------------------------------------
# KALİBRASYON KAYDET / YÜKLE  (JSON dosyası)
# -----------------------------------------------------------------------
KAL_DOSYASI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kalibrasyon.json')

def _monitor_imzasi():
    return [{'x': m.x, 'y': m.y, 'w': m.width, 'h': m.height} for m in ekranlar]

def kalibrasyon_kaydet():
    veri = {
        'monitors':    _monitor_imzasi(),
        'homography':  {k: v.tolist() for k, v in homography_matrices.items()},
        'centers':     {k: list(v)    for k, v in ekran_merkezleri.items()},
    }
    with open(KAL_DOSYASI, 'w', encoding='utf-8') as f:
        json.dump(veri, f, indent=2)
    print(f"💾 Kalibrasyon kaydedildi: {KAL_DOSYASI}")

def kalibrasyon_yukle():
    if not os.path.exists(KAL_DOSYASI):
        return False
    try:
        with open(KAL_DOSYASI, encoding='utf-8') as f:
            veri = json.load(f)
        if veri.get('monitors') != _monitor_imzasi():
            print("⚠️  Monitör yapılandırması değişmiş — kalibrasyon geçersiz, yeniden yap.")
            return False
        homography_matrices.clear()
        ekran_merkezleri.clear()
        for k, v in veri['homography'].items():
            homography_matrices[k] = np.array(v, dtype=np.float32)
        for k, v in veri['centers'].items():
            ekran_merkezleri[k] = tuple(v)
        print("✅ Kalibrasyon yüklendi — kalibrasyon adımı atlandı.")
        return True
    except Exception as e:
        print(f"❌ Kalibrasyon yüklenemedi: {e}")
        return False


def goz_to_screen(rx, ry, H):
    d = cv2.perspectiveTransform(np.array([[[rx,ry]]], dtype=np.float32), H)
    return int(d[0][0][0]), int(d[0][0][1])

def bakilan_ekrani_bul(rx, ry):
    if not ekran_merkezleri: return None
    return min(ekran_merkezleri,
               key=lambda e: math.hypot(rx-ekran_merkezleri[e][0],
                                        ry-ekran_merkezleri[e][1]))

# -----------------------------------------------------------------------
# KAMERA + MEDİAPİPE
# -----------------------------------------------------------------------
mp_face  = mp.solutions.face_mesh
mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils
mp_sty   = mp.solutions.drawing_styles

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

prev_sx, prev_sy = None, None
ALPHA_SMOOTH      = 0.06    # EMA katsayısı — artır = daha hızlı, azalt = daha yumuşak
MAX_DELTA_PX      = 40      # kare başına maksimum imleç hareketi (px)
DEADZONE_PX       = 9       # bu pikselden küçük titreme tamamen yoksayılır
DWELL_LOCK_FRAMES = 20      # bu kadar kare sabit kalınca imleç kilitlenir
_dwell_cd         = 0

_act_lbl    = ''
_act_lbl_cd = 0

if kalibrasyon_yukle():
    adim_indeksi = len(kalibrasyon_adimlari)  # kalibrasyonu atla
    kal_dot.withdraw()
else:
    hedef_goster()

with mp_face.FaceMesh(max_num_faces=1, refine_landmarks=True,
                      min_detection_confidence=0.5,
                      min_tracking_confidence=0.5) as face_mesh, \
     mp_hands.Hands(max_num_hands=1,
                    min_detection_confidence=0.6,
                    min_tracking_confidence=0.6) as hands:

    while cap.isOpened():
        success, frame = cap.read()
        if not success: break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        face_res = face_mesh.process(rgb)
        hand_res = hands.process(rgb)

        goz_rx, goz_ry = 0.5, 0.5
        iris_x, iris_y = w/2.0, h/2.0
        yuz_ok = False
        lm     = None

        if face_res.multi_face_landmarks:
            lm = face_res.multi_face_landmarks[0].landmark
            goz_rx, goz_ry, iris_x, iris_y = bakis_vektoru_hesapla(lm, w, h)
            yuz_ok = True

        zone_ciz(frame, w, h, iris_x, iris_y, yuz_ok)
        if yuz_ok:
            ear_hud(frame, lm, w)

        kalibrasyon_bitti = (adim_indeksi >= len(kalibrasyon_adimlari))

        # ── KALİBRASYON ISITMA (boşluk sonrası kısa bekleme) ────────────
        if not kalibrasyon_bitti and toplama_warmup > 0:
            toplama_warmup -= 1
            cv2.putText(frame, f"Sabit kal... {toplama_warmup}", (10, 165),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)
            if toplama_warmup == 0:
                toplama_aktif  = True
                toplama_buffer = []

        # ── KALİBRASYON TOPLAMA ─────────────────────────────────────────
        if not kalibrasyon_bitti and toplama_aktif and yuz_ok:
            toplama_buffer.append((goz_rx, goz_ry))
            kalan = FRAMES_PER_POINT - len(toplama_buffer)
            cv2.putText(frame, f"TOPLANILIYOR... {kalan}", (10,165),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,100), 2)
            if len(toplama_buffer) >= FRAMES_PER_POINT:
                avg_rx = float(np.mean([p[0] for p in toplama_buffer]))
                avg_ry = float(np.mean([p[1] for p in toplama_buffer]))
                adim = kalibrasyon_adimlari[adim_indeksi]
                ekran_verileri[adim['ekran_adi']]['goz'].append([avg_rx, avg_ry])
                ekran_verileri[adim['ekran_adi']]['screen'].append(
                    [adim['screen_x'], adim['screen_y']])
                print(f"✅ nokta {adim_indeksi%9+1}/9 → ({avg_rx:.4f},{avg_ry:.4f})")
                adim_indeksi  += 1
                toplama_aktif  = False
                toplama_buffer = []
                if adim_indeksi >= len(kalibrasyon_adimlari):
                    haritalari_hesapla()
                    kalibrasyon_kaydet()
                    kal_dot.withdraw()
                    print("\nKALİBRASYON TAMAMLANDI!")
                else:
                    hedef_goster()

        # ── AKTİF TAKİP ─────────────────────────────────────────────────
        if kalibrasyon_bitti:

            # 1) Bakış imlecini konumlandır (sistem faresi hareket etmez)
            if yuz_ok:
                ekr = bakilan_ekrani_bul(goz_rx, goz_ry)
                if ekr and ekr in homography_matrices:
                    hx, hy = goz_to_screen(goz_rx, goz_ry, homography_matrices[ekr])
                    if prev_sx is None:
                        prev_sx, prev_sy = hx, hy

                    dist_moved = math.hypot(hx - prev_sx, hy - prev_sy)
                    if dist_moved > DEADZONE_PX:
                        # Hız sınırı: ani sıçramayı kırp, sonra EMA uygula
                        if dist_moved > MAX_DELTA_PX:
                            ratio = MAX_DELTA_PX / dist_moved
                            hx = int(prev_sx + (hx - prev_sx) * ratio)
                            hy = int(prev_sy + (hy - prev_sy) * ratio)
                        prev_sx = int(ALPHA_SMOOTH * hx + (1 - ALPHA_SMOOTH) * prev_sx)
                        prev_sy = int(ALPHA_SMOOTH * hy + (1 - ALPHA_SMOOTH) * prev_sy)
                        globals()['_dwell_cd'] = DWELL_LOCK_FRAMES
                    elif _dwell_cd > 0:
                        globals()['_dwell_cd'] -= 1

                    # Tkinter bakış imlecini taşı
                    gaz_cur.geometry(f"{GCS}x{GCS}+{prev_sx-GCS//2}+{prev_sy-GCS//2}")
                    if not _gaz_visible:
                        gaz_cur.deiconify()
                        globals()['_gaz_visible'] = True

                    # Hover gönder; interaktif element tespitine göre renk değiştir
                    # _HOVER_EXPAND: element sınırını px cinsinden genişletir (genişletilmiş hitbox)
                    if _gaz_flash_cd == 0:
                        is_link = hover_at_point(prev_sx, prev_sy)
                        if not is_link:
                            # Genişletilmiş hitbox: komşu pikselleri de kontrol et
                            for ox, oy in ((-_HOVER_EXPAND, 0), (_HOVER_EXPAND, 0),
                                           (0, -_HOVER_EXPAND), (0, _HOVER_EXPAND)):
                                if hover_at_point(prev_sx + ox, prev_sy + oy):
                                    is_link = True; break
                        _gaz_renk('yellow' if is_link else 'cyan')

            # 2) Göz kırpma → imlecin bulunduğu konuma tık
            if yuz_ok and lm is not None and prev_sx is not None:
                blink = blink_isle(lm)
                if blink == 'sol_tik':
                    click_at_point(prev_sx, prev_sy, is_right=False)
                    _gaz_flash('lime')
                    _act_lbl = 'SOL TIK ◀'; _act_lbl_cd = 22
                elif blink == 'sag_tik':
                    click_at_point(prev_sx, prev_sy, is_right=True)
                    _gaz_flash('orange')
                    _act_lbl = 'SAG TIK ▶'; _act_lbl_cd = 22

            # 3) Bakış imleci flash sıfırla (hover rengi sonraki kare yeniden belirlenir)
            if _gaz_flash_cd > 0:
                globals()['_gaz_flash_cd'] -= 1

            # 4) El hareketleri → ses / scroll
            if hand_res.multi_hand_landmarks:
                for hi, hlm in enumerate(hand_res.multi_hand_landmarks):
                    mp_draw.draw_landmarks(frame, hlm,
                        mp_hands.HAND_CONNECTIONS,
                        mp_sty.get_default_hand_landmarks_style(),
                        mp_sty.get_default_hand_connections_style())
                    # Sağ el filtresi
                    if hand_res.multi_handedness:
                        if hand_res.multi_handedness[hi].classification[0].label != 'Right':
                            continue
                    thumb_hud(frame, hlm.landmark, w, h)
                    gs = hand_isle(hlm.landmark, prev_sx, prev_sy)
                    nav_lbl = nav_isle(hlm.landmark)
                    if nav_lbl:
                        gs = [nav_lbl] + gs
                        _act_lbl = ' | '.join(gs)
                        _act_lbl_cd = 22 if nav_lbl in ('GERI ◀', 'ILERI ▶') else 7
                    elif gs:
                        _act_lbl = ' | '.join(gs); _act_lbl_cd = 18

        # ── ÖNİZLEME UI ─────────────────────────────────────────────────
        if _act_lbl_cd > 0:
            _act_lbl_cd -= 1
            cv2.putText(frame, _act_lbl, (10, h-16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0,255,200), 2)

        cv2.putText(frame, f"rx:{goz_rx:.3f} ry:{goz_ry:.3f}", (10,28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (220,220,220), 1)

        kalibrasyon_bitti = (adim_indeksi >= len(kalibrasyon_adimlari))
        if not kalibrasyon_bitti:
            n_no = adim_indeksi % 9 + 1
            e_no = adim_indeksi // 9 + 1
            cv2.putText(frame, f"EKRAN {e_no}  Nokta {n_no}/9", (10,55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,200,255), 2)
            cv2.putText(frame, "Kirmizi hedefe bak, kafani sabit tut", (10,82),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0,200,255), 1)
            if not toplama_aktif and toplama_warmup == 0:
                cv2.putText(frame, "BOSLUK: kaydet  |  Q: cik", (10,106),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0,100,255), 1)
        else:
            cv2.putText(frame, "SOL GOZ=LTik  SAG GOZ=RTik", (10,55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0,255,0), 1)
            cv2.putText(frame, "Cimdik+Sol/Sag=Ses  Cimdik+Yukari/Asagi=Scroll", (10,75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180,180,180), 1)
            cv2.putText(frame, "R: yeniden kal.  K: kaydi sil  Q: cik", (10,95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180,180,180), 1)

        cv2.imshow('Kontrol Merkezi', frame)
        root.update()

        key = cv2.waitKey(5) & 0xFF
        if key == 32 and not kalibrasyon_bitti and not toplama_aktif and toplama_warmup == 0:
            if yuz_ok:
                toplama_warmup = WARMUP_FRAMES
            else:
                cv2.putText(frame, "YUZ ALGILANAMADI!", (10,200),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
                cv2.imshow('Kontrol Merkezi', frame)
        elif key == ord('r'):
            ekran_verileri      = {f"EKRAN_{i+1}": {'goz':[], 'screen':[]}
                                   for i in range(toplam_ekran)}
            homography_matrices.clear(); ekran_merkezleri.clear()
            adim_indeksi = 0; toplama_aktif = False; toplama_buffer = []; toplama_warmup = 0
            prev_sx, prev_sy = None, None
            gaz_cur.withdraw(); globals()['_gaz_visible'] = False
            hedef_goster(); print("Kalibrasyon sıfırlandı.")
        elif key == ord('k'):
            if os.path.exists(KAL_DOSYASI):
                os.remove(KAL_DOSYASI)
                print("🗑️  Kayıtlı kalibrasyon silindi.")
            # R ile aynı sıfırlama
            ekran_verileri      = {f"EKRAN_{i+1}": {'goz':[], 'screen':[]}
                                   for i in range(toplam_ekran)}
            homography_matrices.clear(); ekran_merkezleri.clear()
            adim_indeksi = 0; toplama_aktif = False; toplama_buffer = []; toplama_warmup = 0
            prev_sx, prev_sy = None, None
            gaz_cur.withdraw(); globals()['_gaz_visible'] = False
            hedef_goster()
        elif key == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
root.destroy()
