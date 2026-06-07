FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    curl \
    cmake \
    build-essential \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Her adım ayrı: dlib derleme hatası diğer paketleri kesmez
RUN pip install --no-cache-dir numpy==1.26.4
RUN pip install --no-cache-dir dlib==19.24.6
RUN pip install --no-cache-dir mediapipe==0.10.21
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir picamera2 || echo "picamera2 not available (non-RPi platform, skipping)"

COPY . .

RUN mkdir -p /app/data/faces

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
