#!/bin/bash
# 1. System Paths
WORKSPACE="/workspace"
COMFY_DIR="$WORKSPACE/ComfyUI"

# 2. One-time System Installs (Run every boot)
apt-get update && apt-get install -y libsndfile1 ffmpeg build-essential cmake

# 3. Persistence Logic: If ComfyUI isn't there, do a full setup
if [ ! -d "$COMFY_DIR" ]; then
    echo "First-run detected. Setting up persistent volume..."
    cd $WORKSPACE
    git clone https://github.com/comfyanonymous/ComfyUI.git
    cd ComfyUI && pip install -r requirements.txt
    
    # Install Nodes
    cd custom_nodes
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git
    git clone https://github.com/kijai/ComfyUI-LivePortraitKJ.git
    
    # Download Models
    cd $WORKSPACE/SUPERGTX
    python3 download_models.py
else
    echo "Volume detected. Skipping heavy installation..."
fi

# 4. Start Services with Logging
echo "Starting ComfyUI Backend..."
cd $COMFY_DIR && python3 main.py --listen 0.0.0.0 --port 8188 > $WORKSPACE/comfy.log 2>&1 &

echo "Starting SUPERGTX API Bridge..."
cd $WORKSPACE/SUPERGTX && python3 app.py > $WORKSPACE/api.log 2>&1
