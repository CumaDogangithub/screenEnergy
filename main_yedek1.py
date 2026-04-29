# bundan öncesi :şimdi bu kod süper şimdi buna öyle bir özellik ekleyeceğiz ki mükemmel olacak.1 ekranda 3 uygulama açık ben hangisinine bakarsam ona fakuslanacak diğer uygulamalar blurlanacak



import cv2
import mediapipe as mp
import numpy as np
import tkinter as tk
import math
from screeninfo import get_monitors

# --- TKINTER ŞEFFAF DAİRE VE HUD (GÖSTERGE) ---
root = tk.Tk()
root.overrideredirect(True)
root.attributes('-topmost', True)
root.attributes('-transparentcolor', 'black')
root.geometry("0x0+0+0")

canvas = tk.Canvas(root, width=200, height=200, bg='black', highlightthickness=0)
canvas.pack()

# 1. Kırmızı Daire
canvas.create_oval(10, 10, 190, 190, outline='red', width=5)

# 2. Hangi Ekrana Bakıldığını Gösteren Yeşil Metin (Tam Merkezde)
hud_text = canvas.create_text(100, 100, text="HESAPLANIYOR...", fill="lime", font=("Arial", 14, "bold"))

root.withdraw()

# --- MONİTÖR TESPİTİ VE DİZİLİMİ ---
ham_ekranlar = get_monitors()
ekranlar = sorted(ham_ekranlar, key=lambda m: m.x)
toplam_ekran = len(ekranlar)

kalibrasyon_adimlari = []
for i in range(toplam_ekran):
    kalibrasyon_adimlari.extend([
        (f"EKRAN_{i+1}", "SOL UST"),
        (f"EKRAN_{i+1}", "SAG UST"),
        (f"EKRAN_{i+1}", "SAG ALT"),
        (f"EKRAN_{i+1}", "SOL ALT")
    ])

kalibrasyon_verileri = {f"EKRAN_{i+1}": [] for i in range(toplam_ekran)}
adim_indeksi = 0
ekran_sinirlari = {}

def haritalari_hesapla():
    for i, ekran in enumerate(ekranlar):
        ekran_adi = f"EKRAN_{i+1}"
        koseler = kalibrasyon_verileri[ekran_adi]
        
        if len(koseler) == 4:
            min_goz_x = min(k[0] for k in koseler)
            max_goz_x = max(k[0] for k in koseler)
            min_goz_y = min(k[1] for k in koseler)
            max_goz_y = max(k[1] for k in koseler)
            
            min_ekran_x = ekran.x
            max_ekran_x = ekran.x + ekran.width
            min_ekran_y = ekran.y
            max_ekran_y = ekran.y + ekran.height
            
            ekran_sinirlari[ekran_adi] = {
                "goz_x_range": [min_goz_x, max_goz_x],
                "goz_y_range": [min_goz_y, max_goz_y],
                "ekran_x_range": [min_ekran_x, max_ekran_x],
                "ekran_y_range": [min_ekran_y, max_ekran_y],
                "merkez_goz": ((min_goz_x + max_goz_x)/2, (min_goz_y + max_goz_y)/2)
            }

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
cap = cv2.VideoCapture(0,cv2.CAP_DSHOW)

prev_sx, prev_sy = 0, 0
alpha = 0.08 

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

                # Dairenin konumunu güncelle
                root.geometry(f"200x200+{guncel_sx - 100}+{guncel_sy - 100}")
                
                # YENİ: Dairenin içindeki metni anlık olarak güncelle
                canvas.itemconfig(hud_text, text=bakilan_ekran)
                
                root.deiconify() 
            
            root.update()

        cv2.putText(frame, f"Goz Mutlak: X:{goz_x} Y:{goz_y}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        if adim_indeksi < len(kalibrasyon_adimlari):
            hedef_ekran, hedef_kose = kalibrasyon_adimlari[adim_indeksi]
            cv2.putText(frame, f"LUTFEN {hedef_ekran} - {hedef_kose} KOSESINE BAK", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(frame, "KAYDETMEK ICIN 'BOSLUK' TUSUNA BAS", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        else:
            cv2.putText(frame, f"DURUM: AKTIF", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow('Odak Asistani - Stabil Dogrusal', frame)

        key = cv2.waitKey(5) & 0xFF
        if key == 32 and adim_indeksi < len(kalibrasyon_adimlari):
            hedef_ekran, hedef_kose = kalibrasyon_adimlari[adim_indeksi]
            kalibrasyon_verileri[hedef_ekran].append((goz_x, goz_y))
            print(f"✅ {hedef_ekran} - {hedef_kose} kaydedildi! X:{goz_x} Y:{goz_y}")
            
            adim_indeksi += 1
            if adim_indeksi == len(kalibrasyon_adimlari):
                haritalari_hesapla()
                print("\n🎉 STABİL HARİTALAMA TAMAM! KIRMIZI DAİRE VE METİN AKTİF.")
                
        elif key == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
root.destroy()