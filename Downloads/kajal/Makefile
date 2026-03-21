# Kajal — DueDoor Voice Engine
# Makefile for RunPod deployment

.PHONY: help deploy-svara deploy-whisper start-orchestrator logs-svara logs-whisper stop-all

help:
	@echo "Kajal Deployment Commands"
	@echo "========================="
	@echo "make deploy-svara       → Build & push Svara TTS Docker image"
	@echo "make deploy-whisper     → Build & push Whisper STT Docker image"
	@echo "make start-orchestrator → Start Pipecat orchestrator locally"
	@echo "make logs-svara         → Tail Svara pod logs"
	@echo "make logs-whisper       → Tail Whisper pod logs"
	@echo "make stop-all           → Stop all local processes"

# --- Docker image names (update with your Docker Hub / GHCR username) ---
DOCKER_USER ?= duedoor
SVARA_IMAGE  = $(DOCKER_USER)/kajal-svara:latest
WHISPER_IMAGE = $(DOCKER_USER)/kajal-whisper:latest

deploy-svara:
	@echo "→ Building Svara TTS image..."
	docker build -t $(SVARA_IMAGE) ./svara-tts
	docker push $(SVARA_IMAGE)
	@echo "✓ Svara image pushed. Deploy on RunPod using image: $(SVARA_IMAGE)"

deploy-whisper:
	@echo "→ Building Faster-Whisper STT image..."
	docker build -t $(WHISPER_IMAGE) ./whisper-stt
	docker push $(WHISPER_IMAGE)
	@echo "✓ Whisper image pushed. Deploy on RunPod using image: $(WHISPER_IMAGE)"

start-orchestrator:
	@echo "→ Starting Pipecat orchestrator..."
	cd orchestrator && pip install -r requirements.txt -q && python bot.py

logs-svara:
	@echo "Tailing Svara pod logs (requires RunPod CLI)..."
	runpodctl logs svara

logs-whisper:
	@echo "Tailing Whisper pod logs (requires RunPod CLI)..."
	runpodctl logs whisper

stop-all:
	@pkill -f "bot.py" || true
	@echo "✓ Orchestrator stopped."
