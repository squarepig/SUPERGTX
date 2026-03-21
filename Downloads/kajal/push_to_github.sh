#!/bin/bash
# push_to_github.sh
# Run this once to push all Kajal files to your GitHub repo.
# Usage: bash push_to_github.sh YOUR_GITHUB_USERNAME

set -e

GITHUB_USER=${1:-"YOUR_GITHUB_USERNAME"}
REPO_NAME="kajal"
REMOTE="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

echo "========================================"
echo "  Kajal — Pushing to GitHub"
echo "  Repo: ${REMOTE}"
echo "========================================"

# Init git if not already
if [ ! -d ".git" ]; then
  git init
  echo "✓ Git initialized"
fi

# Set remote
if git remote get-url origin &>/dev/null; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi
echo "✓ Remote set: $REMOTE"

# Stage all files
git add .

# Commit
git commit -m "feat: Kajal voice engine — initial commit

- svara-tts/    → Orpheus-based TTS FastAPI pod (RTX 4090)
- whisper-stt/  → Faster-Whisper STT WebSocket pod (RTX 3090)
- orchestrator/ → Pipecat + Claude + Twilio glue (CPU pod)
- supabase/     → Migration for call_logs table
- Makefile      → make deploy-svara / deploy-whisper / start-orchestrator
" || echo "Nothing to commit, already up to date."

# Push
git branch -M main
git push -u origin main

echo ""
echo "========================================"
echo "  ✓ Kajal pushed to GitHub successfully"
echo "  RunPod will auto-deploy on next push."
echo "========================================"
