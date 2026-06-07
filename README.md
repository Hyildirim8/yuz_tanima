# Yüz Tanıma Sistemi

Gerçek zamanlı yüz tanıma ve canlılık tespiti yapan, Docker tabanlı bir web uygulaması.

## Özellikler

- **Yüz Kaydı** — İsimle birlikte yüz kaydetme (HOG + dlib 128-boyutlu embedding)
- **Gerçek Zamanlı Tanıma** — WebSocket üzerinden canlı akış, yeşil/sarı bbox overlay
- **Canlılık Tespiti** — MediaPipe FaceMesh ile göz kırpma (EAR) analizi, replay saldırılarına karşı temel koruma
- **İki Kamera Modu** — Tarayıcı kamerası (WebRTC) veya sunucu kamerası (USB webcam / Raspberry Pi 5 Kamera Modülü)
- **HTTPS** — Aynı ağdaki diğer cihazlardan güvenli erişim için self-signed SSL

## Hızlı Başlangıç

```bash
git clone <repo>
cd yuz_tanima
docker compose up --build
```

Uygulama `http://localhost:3000` adresinde açılır (HTTPS: `https://localhost:3443`).

## Kullanım

1. **Yüz Kaydet** — "Yüzleri Kaydet" → isim gir → Kaydet → 1 kez göz kırp (veya 10 sn sonra "Manuel Yakala")
2. **Tanıma** — Kameranın önüne geç; yeşil kutu = tanındı, sarı = bilinmiyor, kırmızı = canlılık uyarısı
3. **Yüz Sil** — Sağ panelden "Sil" butonu

## Mimari

```
yuz_tanima/
├── docker-compose.yml
├── .env
├── backend/               # FastAPI + uvicorn (port 8000)
│   ├── main.py
│   ├── face_engine.py     # dlib yüz tanıma
│   ├── liveness.py        # MediaPipe EAR göz kırpma
│   ├── camera_capture.py  # Sunucu kamerası (picamera2 / V4L2)
│   ├── native_pool.py     # Tek thread'li native executor (heap güvenliği)
│   ├── api/
│   │   ├── faces.py       # REST: kayıt / liste / sil
│   │   ├── websocket.py   # WS /ws/stream (tarayıcı kamerası)
│   │   └── camera.py      # WS /ws/server-stream + MJPEG
│   └── data/              # volume: yüz görselleri + SQLite
└── frontend/              # nginx (port 3000 HTTP / 3443 HTTPS)
    └── static/
        ├── index.html
        ├── app.js
        └── style.css
```

### Servisler

| Servis    | Image                     | Port       |
|-----------|---------------------------|------------|
| backend   | python:3.11-slim-bookworm | 8000       |
| frontend  | nginx:1.27-alpine         | 3000, 3443 |

## Konfigürasyon

`.env` dosyasını düzenle (`.gitignore` tarafından hariç tutulur):

```env
FACE_TOLERANCE=0.50          # Düşük = katı, yüksek = toleranslı
LIVENESS_EAR_THRESHOLD=0.25  # Göz kırpma hassasiyeti
LIVENESS_BLINKS_REQUIRED=1   # Kaç kırpma gerekli
CORS_ORIGINS=*               # Veya: http://192.168.1.x:3000,...
```

## Raspberry Pi 5 Kamera Modülü

```bash
# RPi 5'te kamera modülünü V4L2 olarak aç
sudo raspi-config → Interface Options → Camera → Enable
echo "dtoverlay=imx708" | sudo tee -a /boot/firmware/config.txt  # Camera Module 3
sudo reboot

# docker-compose.yml içinde devices zaten yapılandırılmış:
#   - "/dev/video0:/dev/video0"
```

Kamera aktifse arayüzde "Sunucu" modu düğmesi aktif olur.

## Aynı Ağdan Erişim

```bash
# Sunucunun IP adresini öğren
ip addr show | grep "inet " | grep -v 127

# Diğer cihazdan bağlan (self-signed sertifika uyarısını kabul et)
https://<sunucu-ip>:3443
```

Tarayıcı kamerası sadece HTTPS üzerinde çalışır (`getUserMedia` kısıtı).

## Geliştirme Notları

- `numpy==1.26.4` sabit — 2.x mediapipe/face_recognition ile uyumsuz
- `native_pool.py` — dlib ve MediaPipe aynı anda farklı thread'lerde çalışınca OpenBLAS heap corruption yapıyor; tek thread'li executor ile serileştirildi
- EAR eşiği 0.25: açık göz ~0.35-0.45, kapalı göz ~0.05-0.15 (MediaPipe normalize koordinatlar)
