import cv2
import mediapipe as mp
import numpy as np
import tkinter as tk
import math
import win32gui
import win32con
import ctypes
from screeninfo import get_monitors

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    pass

# --- MONİTÖR TESPİTİ ---
ham_ekranlar = get_monitors()
ekranlar = sorted(ham_ekranlar, key=lambda m: m.x)
toplam_ekran = len(ekranlar)

min_x_tumu = min(m.x for m in ekranlar)
min_y_tumu = min(m.y for m in ekranlar)
max_x_tumu = max(m.x + m.width  for m in ekranlar)
max_y_tumu = max(m.y + m.height for m in ekranlar)
toplam_genislik  = max_x_tumu - min_x_tumu
toplam_yukseklik = max_y_tumu - min_y_tumu

# --- TKINTER KARARTMA ÖRTÜSÜ ---
root = tk.Tk()
root.overrideredirect(True)
root.attributes('-topmost', True)
root.attributes('-transparentcolor', 'black')
root.attributes('-alpha', 0.85)
root.geometry("0x0+0+0")

canvas = tk.Canvas(root, bg='#111111', highlightthickness=0)
canvas.pack(fill=tk.BOTH, expand=True)

root.update()
overlay_hwnd = win32gui.GetParent(root.winfo_id())
if overlay_hwnd == 0:
    overlay_hwnd = root.winfo_id()
ex_style = win32gui.GetWindowLong(overlay_hwnd, win32con.GWL_EXSTYLE)
win32gui.SetWindowLong(overlay_hwnd, win32con.GWL_EXSTYLE,
                       ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
root.withdraw()

# --- KALİBRASYON HEDEF NOKTASI ---
DOT_R = 20
kal_dot = tk.Toplevel(root)
kal_dot.overrideredirect(True)
kal_dot.attributes('-topmost', True)
kal_dot.attributes('-transparentcolor', 'white')
SIZE = DOT_R * 2 + 8
kal_cv = tk.Canvas(kal_dot, width=SIZE, height=SIZE, bg='white', highlightthickness=0)
kal_cv.pack()
kal_cv.create_oval(4, 4, SIZE - 4, SIZE - 4, fill='red', outline='yellow', width=3)
kal_cv.create_oval(SIZE//2 - 4, SIZE//2 - 4, SIZE//2 + 4, SIZE//2 + 4,
                   fill='white', outline='white')
kal_cv.create_line(SIZE//2, 2, SIZE//2, SIZE - 2, fill='yellow', width=1)
kal_cv.create_line(2, SIZE//2, SIZE - 2, SIZE//2, fill='yellow', width=1)
kal_dot.withdraw()

# --- GÖZ İMLECİ ---
KS = 60
goz_imec = tk.Toplevel(root)
goz_imec.overrideredirect(True)
goz_imec.attributes('-topmost', True)
goz_imec.attributes('-transparentcolor', 'black')
goz_imec_cv = tk.Canvas(goz_imec, width=KS, height=KS, bg='black', highlightthickness=0)
goz_imec_cv.pack()
goz_imec_cv.create_oval(4, 4, KS - 4, KS - 4, outline='cyan', width=2)
goz_imec_cv.create_line(KS // 2, 2,      KS // 2, KS - 2,  fill='cyan', width=1)
goz_imec_cv.create_line(2,       KS // 2, KS - 2, KS // 2, fill='cyan', width=1)
goz_imec_cv.create_oval(KS//2 - 4, KS//2 - 4,
                        KS//2 + 4, KS//2 + 4, fill='cyan', outline='')
goz_imec.withdraw()

goz_imec.update()
imec_hwnd = win32gui.GetParent(goz_imec.winfo_id())
if imec_hwnd == 0:
    imec_hwnd = goz_imec.winfo_id()
imec_ex = win32gui.GetWindowLong(imec_hwnd, win32con.GWL_EXSTYLE)
win32gui.SetWindowLong(imec_hwnd, win32con.GWL_EXSTYLE,
                       imec_ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

imec_gosteriliyor = False

# --- PENCERE BULUCU ---
def get_window_rect_under_gaze(x, y):
    try:
        hwnd      = win32gui.WindowFromPoint((int(x), int(y)))
        hwnd_root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        if hwnd_root == 0:
            hwnd_root = hwnd
        if hwnd_root == overlay_hwnd or not win32gui.IsWindowVisible(hwnd_root):
            return None
        return win32gui.GetWindowRect(hwnd_root)
    except:
        return None

# ---------------------------------------------------------------------------
# BAKIŞ VEKTÖRü  ─  KAMERA KARESİNDE YÜZ KUTUSU + NORMALİZE İRİS
# ---------------------------------------------------------------------------
#
# Eski yaklaşım (solvePnP + iris oranı birleştirme) iki ayrı sinyal üretiyordu
# ve bunların ağırlıklandırılması güçtü. Yeni yaklaşım:
#
#   ► Kamera karesinde sabit bir "yüz kutusu" (ZONE) tanımlanır.
#   ► Her iki iris'in ortalama PIKSELi bu kutuya göre normalize edilir.
#   ► Kafa ötele  → iris kamera'da kayar → oran değişir   ✓
#   ► Kafa döndür → iris kamera'da kayar → oran değişir   ✓
#   ► Sadece gözü döndür → iris kayar     → oran değişir  ✓
#   ► Tek, tutarlı sinyal; karmaşık füzyon yok.
#
# Kullanıcı kafasını bu kutunun içinde tutmalıdır (görsel rehber çizilir).
# ---------------------------------------------------------------------------

# Yüz kutusu (kamera karesinin hangi bölümü)
ZONE_X = (0.08, 0.92)
ZONE_Y = (0.04, 0.96)


def bakis_vektoru_hesapla(lm, w, h):
    """
    Her iki iris'in ortalama kamera pikseli → ZONE içinde normalize → (rx, ry) ∈ [0,1].
    """
    iris_x = (lm[468].x + lm[473].x) / 2.0 * w
    iris_y = (lm[468].y + lm[473].y) / 2.0 * h

    zx1 = ZONE_X[0] * w
    zx2 = ZONE_X[1] * w
    zy1 = ZONE_Y[0] * h
    zy2 = ZONE_Y[1] * h

    goz_rx = float(np.clip((iris_x - zx1) / max(zx2 - zx1, 1), 0.0, 1.0))
    goz_ry = float(np.clip((iris_y - zy1) / max(zy2 - zy1, 1), 0.0, 1.0))

    return goz_rx, goz_ry, iris_x, iris_y


def zone_ciz(frame, w, h, iris_x, iris_y, yuz_algilandi):
    """
    Kamera üzerine yüz kutusunu, oval yüz rehberini ve iris noktasını çizer.
    Renk: kırmızı=yüz yok, turuncu=dışarıda, yeşil=kutunun içinde.
    """
    zx1 = int(ZONE_X[0] * w);  zx2 = int(ZONE_X[1] * w)
    zy1 = int(ZONE_Y[0] * h);  zy2 = int(ZONE_Y[1] * h)
    oz_cx = (zx1 + zx2) // 2;  oz_cy = (zy1 + zy2) // 2

    if not yuz_algilandi:
        renk   = (50, 50, 220)
        etiket = "YUZ ALGILANAMADI!"
    else:
        rx_n = (iris_x - zx1) / max(zx2 - zx1, 1)
        ry_n = (iris_y - zy1) / max(zy2 - zy1, 1)
        icerde = 0.04 <= rx_n <= 0.96 and 0.04 <= ry_n <= 0.96
        if icerde:
            renk   = (0, 210, 0)
            etiket = "KAFANI BU KUTUDA TUT"
        else:
            renk   = (0, 150, 255)
            etiket = "KAFANI MERKEZE AL!"

    # Dış dikdörtgen (ince çizgi)
    cv2.rectangle(frame, (zx1, zy1), (zx2, zy2), renk, 1)

    # Köşe L-işaretleri (kalın)
    cl = 24
    for cx, cy, dx, dy in [(zx1, zy1, 1, 1), (zx2, zy1, -1, 1),
                            (zx2, zy2, -1, -1), (zx1, zy2, 1, -1)]:
        cv2.line(frame, (cx, cy), (cx + dx * cl, cy), renk, 3)
        cv2.line(frame, (cx, cy), (cx, cy + dy * cl), renk, 3)

    # Yüz oval rehberi (gri, arka planda)
    oz_rx = (zx2 - zx1) // 3
    oz_ry = int((zy2 - zy1) * 0.40)
    cv2.ellipse(frame, (oz_cx, oz_cy), (oz_rx, oz_ry), 0, 0, 360, (70, 70, 70), 1)

    # Merkez artı
    cv2.line(frame, (oz_cx - 8, oz_cy), (oz_cx + 8, oz_cy), (60, 60, 60), 1)
    cv2.line(frame, (oz_cx, oz_cy - 8), (oz_cx, oz_cy + 8), (60, 60, 60), 1)

    # Etiket
    cv2.putText(frame, etiket, (zx1 + 4, zy1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, renk, 1)

    if yuz_algilandi:
        ix, iy = int(iris_x), int(iris_y)
        # İris halkası + dolu nokta
        cv2.circle(frame, (ix, iy),  7, (0, 255, 255), -1)
        cv2.circle(frame, (ix, iy), 15, (0, 200, 200),  1)
        # Merkeze ince çizgi
        cv2.line(frame, (ix, iy), (oz_cx, oz_cy), (50, 50, 50), 1)

        # Kutunun kenarlarına yatay/dikey hizalama çizgileri
        cv2.line(frame, (zx1, iy), (ix - 18, iy),  (40, 80, 40), 1)
        cv2.line(frame, (ix + 18, iy), (zx2, iy),  (40, 80, 40), 1)
        cv2.line(frame, (ix, zy1), (ix, iy - 18),  (40, 80, 40), 1)
        cv2.line(frame, (ix, iy + 18), (ix, zy2),  (40, 80, 40), 1)


# --- 9 NOKTA KALİBRASYON ---
IZGARA          = [(fx, fy) for fy in [0.1, 0.5, 0.9] for fx in [0.1, 0.5, 0.9]]
FRAMES_PER_POINT = 30

kalibrasyon_adimlari = []
for i, ekran in enumerate(ekranlar):
    for fx, fy in IZGARA:
        kalibrasyon_adimlari.append({
            'ekran_idx': i,
            'ekran_adi': f"EKRAN_{i+1}",
            'screen_x': int(ekran.x + fx * ekran.width),
            'screen_y': int(ekran.y + fy * ekran.height),
        })

ekran_verileri     = {f"EKRAN_{i+1}": {'goz': [], 'screen': []} for i in range(toplam_ekran)}
homography_matrices = {}
ekran_merkezleri    = {}

adim_indeksi   = 0
toplama_aktif  = False
toplama_buffer = []


def hedef_goster():
    if adim_indeksi >= len(kalibrasyon_adimlari):
        kal_dot.withdraw()
        return
    adim = kalibrasyon_adimlari[adim_indeksi]
    kal_dot.geometry(f"{SIZE}x{SIZE}+{adim['screen_x'] - SIZE//2}+{adim['screen_y'] - SIZE//2}")
    kal_dot.deiconify()
    kal_dot.lift()


def haritalari_hesapla():
    for ekran_adi, veri in ekran_verileri.items():
        if len(veri['goz']) < 4:
            continue
        src = np.array(veri['goz'],    dtype=np.float32)
        dst = np.array(veri['screen'], dtype=np.float32)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=50.0)
        if H is not None:
            homography_matrices[ekran_adi] = H
            inliers = int(mask.sum()) if mask is not None else len(src)
            print(f"{ekran_adi}: homography hazir ({inliers}/{len(src)} nokta)")
        ekran_merkezleri[ekran_adi] = (float(np.mean(src[:, 0])),
                                       float(np.mean(src[:, 1])))
    root.geometry(f"{toplam_genislik}x{toplam_yukseklik}+{min_x_tumu}+{min_y_tumu}")


def goz_to_screen(rx, ry, H):
    src = np.array([[[rx, ry]]], dtype=np.float32)
    dst = cv2.perspectiveTransform(src, H)
    return int(dst[0][0][0]), int(dst[0][0][1])


def bakilan_ekrani_bul(rx, ry):
    if not ekran_merkezleri:
        return None
    return min(ekran_merkezleri,
               key=lambda e: math.hypot(rx - ekran_merkezleri[e][0],
                                        ry - ekran_merkezleri[e][1]))


# --- KAMERA VE MEDIAPIPE ---
mp_face_mesh = mp.solutions.face_mesh
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

prev_sx, prev_sy = None, None
ALPHA_SMOOTH     = 0.07   # küçük → yumuşak, titremesiz hareket

hedef_goster()

with mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
) as face_mesh:

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        frame     = cv2.flip(frame, 1)
        h, w, _   = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results   = face_mesh.process(rgb_frame)

        goz_rx, goz_ry = 0.5, 0.5
        iris_x, iris_y = w / 2.0, h / 2.0
        yuz_algilandi  = False

        if results.multi_face_landmarks:
            lm = results.multi_face_landmarks[0].landmark
            goz_rx, goz_ry, iris_x, iris_y = bakis_vektoru_hesapla(lm, w, h)
            yuz_algilandi = True

        # Her zaman yüz kutusunu çiz
        zone_ciz(frame, w, h, iris_x, iris_y, yuz_algilandi)

        kalibrasyon_bitti = (adim_indeksi >= len(kalibrasyon_adimlari))

        # --- KALİBRASYON TOPLAMA ---
        if not kalibrasyon_bitti and toplama_aktif and yuz_algilandi:
            toplama_buffer.append((goz_rx, goz_ry))
            kalan = FRAMES_PER_POINT - len(toplama_buffer)
            cv2.putText(frame, f"TOPLANILIYOR... {kalan:2d}", (10, 165),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 100), 2)

            if len(toplama_buffer) >= FRAMES_PER_POINT:
                avg_rx = float(np.mean([p[0] for p in toplama_buffer]))
                avg_ry = float(np.mean([p[1] for p in toplama_buffer]))
                adim   = kalibrasyon_adimlari[adim_indeksi]
                ekran_verileri[adim['ekran_adi']]['goz'].append([avg_rx, avg_ry])
                ekran_verileri[adim['ekran_adi']]['screen'].append(
                    [adim['screen_x'], adim['screen_y']])
                print(f"✅ {adim['ekran_adi']} nokta {adim_indeksi % 9 + 1}/9 "
                      f"→ ({avg_rx:.4f}, {avg_ry:.4f})")

                adim_indeksi  += 1
                toplama_aktif  = False
                toplama_buffer = []

                if adim_indeksi >= len(kalibrasyon_adimlari):
                    haritalari_hesapla()
                    kal_dot.withdraw()
                    print("\nKALİBRASYON TAMAMLANDI! Odak asistanı aktif.")
                else:
                    hedef_goster()

        # --- AKTİF TAKİP ---
        if kalibrasyon_bitti and yuz_algilandi:
            bakilan_ekran = bakilan_ekrani_bul(goz_rx, goz_ry)

            if bakilan_ekran and bakilan_ekran in homography_matrices:
                H = homography_matrices[bakilan_ekran]
                hedef_sx, hedef_sy = goz_to_screen(goz_rx, goz_ry, H)

                if prev_sx is None:
                    prev_sx, prev_sy = hedef_sx, hedef_sy

                guncel_sx = int(ALPHA_SMOOTH * hedef_sx + (1 - ALPHA_SMOOTH) * prev_sx)
                guncel_sy = int(ALPHA_SMOOTH * hedef_sy + (1 - ALPHA_SMOOTH) * prev_sy)
                prev_sx, prev_sy = guncel_sx, guncel_sy

                goz_imec.geometry(f"{KS}x{KS}+{guncel_sx - KS//2}+{guncel_sy - KS//2}")
                if not imec_gosteriliyor:
                    goz_imec.deiconify()
                    imec_gosteriliyor = True

                app_rect = get_window_rect_under_gaze(guncel_sx, guncel_sy)
                canvas.delete("all")
                if app_rect:
                    left  = app_rect[0] - min_x_tumu
                    top   = app_rect[1] - min_y_tumu
                    right = app_rect[2] - min_x_tumu
                    bot   = app_rect[3] - min_y_tumu
                    canvas.create_rectangle(left, top, right, bot,
                                            fill='black', outline='lime', width=5)
                root.deiconify()

        # --- KAMERA ÖNİZLEME DURUM METİNLERİ ---
        cv2.putText(frame, f"rx:{goz_rx:.3f}  ry:{goz_ry:.3f}", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

        kalibrasyon_bitti = (adim_indeksi >= len(kalibrasyon_adimlari))

        if not kalibrasyon_bitti:
            nokta_no = adim_indeksi % 9 + 1
            ekran_no = adim_indeksi // 9 + 1
            cv2.putText(frame, f"EKRAN {ekran_no}  Nokta {nokta_no}/9", (10, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2)
            cv2.putText(frame, "Kirmizi hedefe bak, kafani sabit tut", (10, 82),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 200, 255), 1)
            if not toplama_aktif:
                cv2.putText(frame, "BOSLUK: kaydet  |  Q: cik", (10, 106),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 100, 255), 1)
        else:
            cv2.putText(frame, "ODAK ASISTANI AKTIF", (10, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, "R: yeniden kalibrasyon  |  Q: cik", (10, 82),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (200, 200, 200), 1)

        cv2.imshow('Odak Asistani', frame)
        root.update()

        key = cv2.waitKey(5) & 0xFF
        if key == 32 and not kalibrasyon_bitti and not toplama_aktif:
            if yuz_algilandi:
                toplama_aktif  = True
                toplama_buffer = []
            else:
                cv2.putText(frame, "YUZ ALGILANAMADI!", (10, 195),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                cv2.imshow('Odak Asistani', frame)
        elif key == ord('r'):
            ekran_verileri      = {f"EKRAN_{i+1}": {'goz': [], 'screen': []}
                                   for i in range(toplam_ekran)}
            homography_matrices.clear()
            ekran_merkezleri.clear()
            adim_indeksi      = 0
            toplama_aktif     = False
            toplama_buffer    = []
            prev_sx, prev_sy  = None, None
            imec_gosteriliyor = False
            goz_imec.withdraw()
            root.withdraw()
            hedef_goster()
            print("Kalibrasyon sifirlandı.")
        elif key == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
root.destroy()
