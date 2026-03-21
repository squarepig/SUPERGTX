# Kajal — Faster-Whisper STT Pod
# GPU: RTX 3090 / A4000 (8GB+ VRAM sufficient)

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model weights at build time
COPY download_model.py .
RUN python download_model.py

COPY server.py .

EXPOSE 8001

# Global Singleton: model loads once, WebSocket stays warm
CMD ["python", "server.py"]
