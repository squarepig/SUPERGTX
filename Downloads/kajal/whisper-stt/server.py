"""
server.py — Kajal Faster-Whisper STT WebSocket Service
Runs on RunPod GPU Pod (RTX 3090 / A4000)

Global Singleton pattern: model loads ONCE on startup.
Streams audio chunks in, returns transcribed text instantly.
Audio format: 16kHz mono PCM (matches Twilio + Svara expectations)
"""

import os
import asyncio
import logging
import json
import numpy as np
import websockets
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_SIZE  = os.getenv("WHISPER_MODEL_SIZE", "medium")
CACHE_DIR   = "/app/whisper_cache"
DEVICE      = "cuda"
COMPUTE     = "float16"
SAMPLE_RATE = 16000            # 16kHz mono PCM — sweet spot for Whisper
PORT        = int(os.getenv("PORT", 8001))
LANGUAGE    = os.getenv("WHISPER_LANGUAGE", None)   # None = auto-detect

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kajal-stt")

# ---------------------------------------------------------------------------
# Global Singleton — loaded ONCE at process start
# ---------------------------------------------------------------------------
log.info(f"Loading faster-whisper [{MODEL_SIZE}] on {DEVICE}...")
whisper_model = WhisperModel(
    MODEL_SIZE,
    device=DEVICE,
    compute_type=COMPUTE,
    download_root=CACHE_DIR,
)
log.info("✓ Whisper model loaded and warm.")

# ---------------------------------------------------------------------------
# VAD helper — simple energy-based VAD
# (SileroVAD used in Pipecat orchestrator for production interruption handling)
# ---------------------------------------------------------------------------
def has_speech(audio_chunk: np.ndarray, threshold: float = 0.01) -> bool:
    rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
    return rms > threshold * 32768

# ---------------------------------------------------------------------------
# WebSocket handler
# Each call gets its own connection; audio bytes stream in, text streams out
# ---------------------------------------------------------------------------
async def handle_connection(websocket, path):
    client = websocket.remote_address
    log.info(f"[STT] New connection from {client}")

    audio_buffer = bytearray()

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Accumulate PCM bytes
                audio_buffer.extend(message)

                # Transcribe when we have ~0.5s of audio (16kHz × 2 bytes × 0.5s = 16000 bytes)
                if len(audio_buffer) >= 16000:
                    audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
                    audio_buffer.clear()

                    if not has_speech(audio_np):
                        continue

                    # Run Whisper inference
                    segments, info = whisper_model.transcribe(
                        audio_np,
                        language=LANGUAGE,
                        beam_size=5,
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 300},
                    )

                    text = " ".join(s.text for s in segments).strip()
                    if text:
                        log.info(f"[STT] Transcribed: '{text}' (lang={info.language})")
                        await websocket.send(json.dumps({
                            "type": "transcript",
                            "text": text,
                            "language": info.language,
                            "is_final": True,
                        }))

            elif isinstance(message, str):
                cmd = json.loads(message)
                if cmd.get("type") == "clear_buffer":
                    audio_buffer.clear()
                    log.info(f"[STT] Buffer cleared for {client}")

    except websockets.exceptions.ConnectionClosed:
        log.info(f"[STT] Connection closed: {client}")
    except Exception as e:
        log.error(f"[STT] Error: {e}", exc_info=True)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    log.info(f"Kajal STT WebSocket server starting on port {PORT}...")
    async with websockets.serve(handle_connection, "0.0.0.0", PORT, max_size=10 * 1024 * 1024):
        log.info(f"✓ Kajal STT ready on ws://0.0.0.0:{PORT}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
