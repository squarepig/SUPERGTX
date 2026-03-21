"""
download_model.py
Run at Docker BUILD time to pre-bake model weights into the image.
This eliminates cold-start latency on RunPod pod restarts.
"""

from huggingface_hub import snapshot_download
import os

MODEL_ID = os.getenv("SVARA_MODEL_ID", "canopylabs/orpheus-3b-0.1-ft")
CACHE_DIR = "/app/model_cache"

print(f"Pre-downloading model: {MODEL_ID}")
snapshot_download(
    repo_id=MODEL_ID,
    cache_dir=CACHE_DIR,
    ignore_patterns=["*.msgpack", "*.h5", "flax_model*"],
)
print("✓ Model weights cached successfully.")
