"""
server.py — Kajal Svara-TTS FastAPI Service
Runs on RunPod GPU Pod (RTX 4090 / A6000)

Global Singleton pattern: model loads ONCE on startup,
stays warm for zero-latency streaming inference.
"""

import os
import json
import asyncio
import logging
from typing import AsyncGenerator

import torch
import soundfile as sf
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_ID    = os.getenv("SVARA_MODEL_ID", "canopylabs/orpheus-3b-0.1-ft")
CACHE_DIR   = "/app/model_cache"
VOICE_NAME  = os.getenv("KAJAL_VOICE", "kajal")   # custom trained voice
SAMPLE_RATE = 24000
DEVICE      = "cuda" if torch.cuda.is_available() else "cpu"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kajal-tts")

# ---------------------------------------------------------------------------
# Global Singleton — loaded ONCE at startup
# ---------------------------------------------------------------------------
tts_pipeline = None

def load_model():
    global tts_pipeline
    log.info(f"Loading Svara/Orpheus model on {DEVICE}...")
    # Import here so Docker layer caching works cleanly
    import sys
    sys.path.insert(0, "/app/orpheus")
    from inference import OrpheusTTS  # Orpheus-TTS inference class

    tts_pipeline = OrpheusTTS(
        model_id=MODEL_ID,
        cache_dir=CACHE_DIR,
        device=DEVICE,
    )
    log.info("✓ Kajal TTS model loaded and warm.")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="Kajal TTS", version="1.0.0")

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, load_model)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice: str = VOICE_NAME
    emotion: str = "neutral"      # neutral | happy | empathetic | clear
    language: str = "hi-en"       # Hinglish default; supports 19 Indic langs
    stream: bool = True

# ---------------------------------------------------------------------------
# Emotion tag mapper — appended to text before inference
# Svara/Orpheus supports inline emotion tags
# ---------------------------------------------------------------------------
EMOTION_TAGS = {
    "neutral":    "",
    "happy":      "<happy>",
    "empathetic": "<empathetic>",
    "clear":      "<clear>",
    "excited":    "<excited>",
}

def apply_emotion(text: str, emotion: str) -> str:
    tag = EMOTION_TAGS.get(emotion, "")
    return f"{tag}{text}" if tag else text

# ---------------------------------------------------------------------------
# Streaming audio generator
# ---------------------------------------------------------------------------
async def stream_audio(text: str, voice: str, emotion: str, language: str) -> AsyncGenerator[bytes, None]:
    tagged_text = apply_emotion(text, emotion)
    log.info(f"[TTS] voice={voice} emotion={emotion} lang={language} → '{tagged_text[:60]}...'")

    loop = asyncio.get_event_loop()

    def _generate():
        # tts_pipeline.stream() yields audio chunks as numpy arrays
        for audio_chunk in tts_pipeline.stream(
            text=tagged_text,
            voice=voice,
            language=language,
            sample_rate=SAMPLE_RATE,
        ):
            # Convert float32 numpy → 16-bit PCM bytes
            pcm = (audio_chunk * 32767).astype(np.int16)
            yield pcm.tobytes()

    for chunk in _generate():
        yield chunk
        await asyncio.sleep(0)   # yield control to event loop

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/v1/text-to-speech")
async def text_to_speech(req: TTSRequest):
    if tts_pipeline is None:
        raise HTTPException(503, "Model not loaded yet. Retry in a moment.")

    if req.stream:
        return StreamingResponse(
            stream_audio(req.text, req.voice, req.emotion, req.language),
            media_type="audio/pcm",
            headers={
                "X-Sample-Rate": str(SAMPLE_RATE),
                "X-Channels": "1",
                "X-Bit-Depth": "16",
            },
        )
    else:
        # Non-streaming: return full WAV
        tagged_text = apply_emotion(req.text, req.emotion)
        audio_np = tts_pipeline.synthesize(
            text=tagged_text,
            voice=req.voice,
            language=req.language,
            sample_rate=SAMPLE_RATE,
        )
        import io
        buf = io.BytesIO()
        sf.write(buf, audio_np, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return StreamingResponse(buf, media_type="audio/wav")

@app.get("/health")
async def health():
    return {
        "status": "ok" if tts_pipeline is not None else "loading",
        "device": DEVICE,
        "voice": VOICE_NAME,
        "model": MODEL_ID,
    }
