#!/bin/bash
# Run this on YOUR machine (not in Claude's container)
# This pushes all Kajal files to your GitHub repo

# Step 1: Clone or create the repo locally
# If repo is empty on GitHub, just do:
git clone https://github.com/vshlpathak63/kajal.git
cd kajal

# Step 2: Copy files from this output into the repo
# (Download the zip from the outputs folder or copy files manually)

# Step 3: Push
git add .
git commit -m "feat: Kajal voice engine — initial commit"
git branch -M main
git push -u origin main

echo "✓ Done! RunPod will auto-deploy on next push."
