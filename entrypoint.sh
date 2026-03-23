#!/bin/bash

# 1. SETUP PERSISTENT PATHS (CRITICAL for "No Space" Fix)
export WORKSPACE="/workspace"
export COMFY_DIR="$WORKSPACE/ComfyUI"
export SUPERGTX_DIR="$WORKSPACE/SUPERGTX"

# Redirect all Python/Pip activity to the 50GB Volume
export PIP_CACHE_DIR="$WORKSPACE/pip_cache"
export PYTHONUSERBASE="$WORKSPACE/python_libs"
export PATH="$PYTHONUSERBASE/bin:$PATH"

mkdir -p $PIP_CACHE_DIR
mkdir -p $PYTHONUSERBASE

echo "--- Starting DueDoor AI Engine (Restart-Proof Mode) ---"

# 2. SYSTEM DEPENDENCIES (Run every boot)
apt-get update && apt-get install -y libsndfile1 ffmpeg build-essential cmake

# 3. SMART INSTALLATION LOGIC
if [ ! -d "$COMFY_DIR" ]; then
    echo "First-run detected. Initializing Persistent Volume..."
    cd $WORKSPACE
    
    # Clone ComfyUI
    git clone https://github.com/comfyanonymous/ComfyUI.git
    cd $COMFY_DIR && pip install --user -r requirements.txt
    
    # Install High-Performance Custom Nodes
    cd custom_nodes
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git
    git clone https://github.com/kijai/ComfyUI-LivePortraitKJ.git
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
    
    # Install Node Requirements (Redirecting to 50GB Volume)
    cd ComfyUI-WanVideoWrapper && pip install --user -r requirements.txt
    cd ../ComfyUI-LivePortraitKJ && pip install --user -r requirements.txt
    
    # Run Model Downloader
    cd $SUPERGTX_DIR
    python3 download_models.py
else
    echo "Volume Detected. Skipping heavy installations."
fi

# 4. API & SVARA SETUP
echo "Checking Bridge Dependencies..."
cd $SUPERGTX_DIR
# Using --user and --break-system-packages to bypass the 'blinker' error safely
pip install --user pynini==2.1.5 
pip install --user -r requirements.txt --break-system-packages --ignore-installed blinker

# 5. LAUNCH SERVICES (Optimized for RTX A5000 20GB VRAM)
echo "Launching ComfyUI Backend..."
cd $COMFY_DIR
python3 main.py --listen 0.0.0.0 --port 8188 --lowvram --preview-method auto > $WORKSPACE/comfy.log 2>&1 &

echo "Launching SUPERGTX API Bridge..."
cd $SUPERGTX_DIR
python3 app.py > $WORKSPACE/api.log 2>&1
