#!/bin/bash

# 1. SETUP PERSISTENT PATHS
WORKSPACE="/workspace"
COMFY_DIR="$WORKSPACE/ComfyUI"
SUPERGTX_DIR="$WORKSPACE/SUPERGTX"

echo "--- Starting DueDoor AI Engine Setup ---"

# 2. SYSTEM DEPENDENCIES (Required every boot as they are in the container layer)
echo "Installing system-level dependencies..."
apt-get update && apt-get install -y libsndfile1 ffmpeg build-essential cmake

# 3. SMART INSTALLATION LOGIC
if [ ! -d "$COMFY_DIR" ]; then
    echo "First-run detected. Initializing Persistent Volume (50GB)..."
    cd $WORKSPACE
    
    # Clone ComfyUI Core
    git clone https://github.com/comfyanonymous/ComfyUI.git
    cd $COMFY_DIR && pip install -r requirements.txt
    
    # Install High-Performance Custom Nodes for Real Estate Reels
    cd custom_nodes
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git
    git clone https://github.com/kijai/ComfyUI-LivePortraitKJ.git
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
    
    # Install Node Requirements
    cd ComfyUI-WanVideoWrapper && pip install -r requirements.txt
    cd ../ComfyUI-LivePortraitKJ && pip install -r requirements.txt
    
    # Run the Model Downloader for Wan 2.1 (FP8) and LivePortrait
    echo "Downloading AI Weights..."
    cd $SUPERGTX_DIR
    python3 download_models.py
else
    echo "Persistent Volume Detected. Skipping heavy installations."
fi

# 4. ENVIRONMENT PREP
echo "Ensuring Svara and API dependencies are ready..."
cd $SUPERGTX_DIR
pip install pynini==2.1.5  # Critical for Svara
pip install -r requirements.txt

# 5. LAUNCH SERVICES (Optimized for RTX A5000 20GB VRAM)
echo "Launching ComfyUI Backend (Low VRAM Mode)..."
cd $COMFY_DIR
# We use --lowvram to ensure Wan 2.1 and Svara can share the 20GB memory
python3 main.py --listen 0.0.0.0 --port 8188 --lowvram --preview-method auto > $WORKSPACE/comfy.log 2>&1 &

echo "Launching SUPERGTX API Bridge..."
cd $SUPERGTX_DIR
python3 app.py > $WORKSPACE/api.log 2>&1
