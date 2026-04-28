import cv2
import mediapipe as mp
import numpy as np
import tkinter as tk
import math
import win32gui
import win32con
import ctypes
from screeninfo import get_monitors

# --- WINDOWS DPI ÖLÇEKLENDİRME HATASINI ÇÖZ ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    pass

# --- MONİTÖR TESPİTİ VE DİZİLİMİ ---
ham_ekranlar = get_monitors()
ekranlar = sorted(ham_ekranlar, key=lambda m: m.x)
toplam_ekran = len(ekranlar)

# Tüm monitörleri kapsayan en geniş sınırları buluyoruz (Devasa Örtü İçin)
min_x_tumu = min(m.x for m in ekranlar)
min_y_tumu = min(m.y for m in ekranlar)
max_x_tumu = max(m.x + m.width for m in ekranlar)
max_y_tumu = max(m.y + m.height for m in ekranlar)
toplam_genislik = max_x_tumu - min_x_tumu
toplam_yukseklik = max_y_tumu - min_y_tumu

# --- TKINTER DEVASA KARARTMA ÖRTÜSÜ ---
root = tk.Tk()
root.overrideredirect(True)
root.attributes('-topmost', True)
root.attributes('-transparentcolor', 'black') # Siyah renk "Delik/Şeffaf" olacak
root.attributes('-alpha', 0.85) # Geri kalan her yer %85 karartılacak
root.geometry("0x0+0+0")

# Arka plan koyu gri (Karartma efekti). Siyah yapmıyoruz çünkü siyahlar şeffaf olacak.
canvas = tk.Canvas(root, bg='#111111', highlightthickness=0)
canvas.pack(fill=tk.BOTH, expand=True)
root.withdraw()

def make_click_through(hwnd):
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

# --- UYGULAMA (PENCERE) BULUCU API ---
def get_window_rect_under_gaze(x, y):
    try:
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        hwnd_root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        if hwnd_root == 0: hwnd_root = hwnd
        rect = win32gui.GetWindowRect(hwnd_root)
        return rect
    except:
        return None

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
                "merkez_goz": (sum(k[0] for k in koseler)/4, sum(k[1] for k in koseler)/4)
            }
    # Kalibrasyon bitince devasa örtüyü tüm ekranlara yay
    root.geometry(f"{toplam_genislik}x{toplam_yukseklik}+{min_x_tumu}+{min_y_tumu}")

def bakilan_ekrani_bul(g_x, g_y):
    if adim_indeksi < len(kalibrasyon_adimlari): return None
    min_mesafe = float('inf')
    bulunan_ekran = None
    for ekran_adi, sinirlar in ekran_sinirlari.items():
        m_x, m_y = sinirlar["merkez_goz"]
        mesafe = math.hypot(g_x - m_x, g_y - m_y)
        if mesafe < min_mesafe:
            min_mesafe = mesafe
            bulunan_ekran = ekran_adi
    return bulunan_ekran

# --- YAPAY ZEKA VE KAMERA ---
mp_face_mesh = mp.solutions.face_mesh
cap = cv2.VideoCapture(0)

prev_sx, prev_sy = 0, 0
alpha = 0.1 

with mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True, 
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
) as face_mesh:

    while cap.isOpened():
        success, frame = cap.read()
        if not success: break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)

        goz_x, goz_y = 0, 0

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                left_iris = face_landmarks.landmark[468]
                goz_x = int(left_iris.x * w)
                goz_y = int(left_iris.y * h)
                cv2.circle(frame, (goz_x, goz_y), 5, (0, 255, 255), -1)

        if adim_indeksi == len(kalibrasyon_adimlari):
            bakilan_ekran = bakilan_ekrani_bul(goz_x, goz_y)
            
            if bakilan_ekran:
                snr = ekran_sinirlari[bakilan_ekran]
                
                hedef_sx = np.interp(goz_x, snr["goz_x_range"], snr["ekran_x_range"])
                hedef_sy = np.interp(goz_y, snr["goz_y_range"], snr["ekran_y_range"])

                if prev_sx == 0: prev_sx, prev_sy = hedef_sx, hedef_sy
                guncel_sx = int(alpha * hedef_sx + (1 - alpha) * prev_sx)
                guncel_sy = int(alpha * hedef_sy + (1 - alpha) * prev_sy)
                prev_sx, prev_sy = guncel_sx, guncel_sy

                app_rect = get_window_rect_under_gaze(guncel_sx, guncel_sy)

                # Tuvali tamamen temizle
                canvas.delete("all") 
                
                # 1. UYGULAMAYI AYDINLAT VE YEŞİL ÇİZGİ ÇEK
                if app_rect:
                    # Tkinter'ın devasa tuvalindeki göreceli koordinatları hesapla
                    left = app_rect[0] - min_x_tumu
                    top = app_rect[1] - min_y_tumu
                    right = app_rect[2] - min_x_tumu
                    bottom = app_rect[3] - min_y_tumu

                    # fill='black' dediğimiz için bu alan CAM GİBİ ŞEFFAF olacak (Karartma kalkacak)
                    canvas.create_rectangle(left, top, right, bottom, fill='black', outline='lime', width=5)

                # 2. KIRMIZI TAKİP DAİRESİNİ ÇİZ (Senin nereye baktığını gösteren hedef)
                cx = guncel_sx - min_x_tumu
                cy = guncel_sy - min_y_tumu
                canvas.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, outline='red', width=3)

                root.deiconify() 
                
                if not hasattr(root, 'click_through_set'):
                    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                    if hwnd == 0: hwnd = root.winfo_id()
                    make_click_through(hwnd)
                    root.click_through_set = True
            
            root.update()

        cv2.putText(frame, f"Goz: X:{goz_x} Y:{goz_y}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        if adim_indeksi < len(kalibrasyon_adimlari):
            hedef_ekran, hedef_kose = kalibrasyon_adimlari[adim_indeksi]
            cv2.putText(frame, f"LUTFEN {hedef_ekran} - {hedef_kose} KOSESINE BAK", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(frame, "KAYDETMEK ICIN 'BOSLUK' TUSUNA BAS", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        else:
            cv2.putText(frame, f"DURUM: ODAK ASISTANI AKTIF", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow('Odak Asistani - Tam Surum', frame)

        key = cv2.waitKey(5) & 0xFF
        if key == 32 and adim_indeksi < len(kalibrasyon_adimlari):
            hedef_ekran, hedef_kose = kalibrasyon_adimlari[adim_indeksi]
            kalibrasyon_verileri[hedef_ekran].append((goz_x, goz_y))
            
            adim_indeksi += 1
            if adim_indeksi == len(kalibrasyon_adimlari):
                haritalari_hesapla()
                print("\n🎉 VİZYON GERÇEKLEŞTİ! KARARTMA, YEŞİL ÇERÇEVE VE KIRMIZI DAİRE AKTİF.")
                
        elif key == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
root.destroy()