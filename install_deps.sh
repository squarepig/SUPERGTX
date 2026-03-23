#!/bin/bash
apt-get update && apt-get install -y libsndfile1 ffmpeg build-essential cmake
pip install pynini==2.1.5
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI/custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Manager.git
git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git
git clone https://github.com/kijai/ComfyUI-LivePortraitKJ.git
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
echo "Infrastructure setup complete. Remember to download model weights next."
