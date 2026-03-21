# Kajal — Svara TTS Pod
# GPU: RTX 4090 / A6000 (16GB+ VRAM required)

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone Svara-TTS (Orpheus-based)
RUN git clone https://github.com/canopyai/Orpheus-TTS.git /app/orpheus

# Pre-download model weights at build time (avoids cold-start latency)
COPY download_model.py .
RUN python download_model.py

# Copy FastAPI server
COPY server.py .
COPY kajal_voice.json .

EXPOSE 8000

# Load model ONCE on startup — Global Singleton pattern
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
