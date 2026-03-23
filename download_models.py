import os
import subprocess

def download_hf_model(repo_id, filename, local_dir):
    os.makedirs(local_dir, exist_ok=True)
    print(f"Checking for {filename} in {local_dir}...")
    subprocess.run([
        "huggingface-cli", "download", repo_id, filename,
        "--local-dir", local_dir, "--local-dir-use-symlinks", "False"
    ])

# 1. Wan 2.1 1.3B (The "Speed" version for 15s reels)
download_hf_model("Kijai/WanVideo_comfy_fp8_scaled", "wan2.1_i2v_1.3b_f8_scaled.safetensors", "/workspace/ComfyUI/models/diffusion_models")

# 2. LivePortrait Weights
download_hf_model("Kijai/liveportrait_fp16_comfy", "appearance_feature_extractor.safetensors", "/workspace/ComfyUI/models/liveportrait")

# 3. Svara-TTS Weights (Note: Place your .nemo file manually in /workspace/models/svara/ if not on HF)
print("Manual Check: Ensure svara_v1.nemo is in /workspace/models/svara/")
