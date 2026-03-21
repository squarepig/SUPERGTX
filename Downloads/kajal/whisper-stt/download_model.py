"""
download_model.py
Pre-downloads Whisper model weights into the Docker image at build time.
"""
from faster_whisper import WhisperModel
import os

MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")
CACHE_DIR  = "/app/whisper_cache"

print(f"Pre-downloading faster-whisper model: {MODEL_SIZE}")
# Instantiating downloads and caches the model
model = WhisperModel(MODEL_SIZE, device="cpu", download_root=CACHE_DIR)
print("✓ Whisper model cached.")
