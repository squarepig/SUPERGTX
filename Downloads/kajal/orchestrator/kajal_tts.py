"""
kajal_tts.py — Pipecat TTS service wrapping Kajal's Svara RunPod pod

Key behaviour:
- Streams text chunks from Claude → Svara TTS endpoint as they arrive
- Returns streaming PCM audio back to Pipecat pipeline
- Sends CancelFrame-compatible abort signal when user interrupts
"""

import asyncio
import httpx
import numpy as np
from loguru import logger
from pipecat.services.ai_services import TTSService
from pipecat.frames.frames import AudioRawFrame, TTSAudioRawFrame


# Emotion inference from Claude output keywords
def infer_emotion(text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ["congratulations", "great", "wonderful", "happy", "excited"]):
        return "happy"
    if any(w in text_lower for w in ["understand", "sorry", "concern", "budget", "difficult"]):
        return "empathetic"
    if any(w in text_lower for w in ["price", "sq ft", "rera", "possession", "floor"]):
        return "clear"
    return "neutral"


class KajalSvaraTTSService(TTSService):
    """
    Sends streamed text to the Kajal Svara-TTS pod on RunPod
    and pushes PCM audio chunks into the Pipecat pipeline.
    """

    def __init__(self, base_url: str, voice: str = "kajal", language: str = "hi-en", **kwargs):
        super().__init__(**kwargs)
        self._base_url = base_url.rstrip("/")
        self._voice = voice
        self._language = language

    async def run_tts(self, text: str) -> None:
        """Stream text to Svara TTS and push audio frames."""
        if not text.strip():
            return

        emotion = infer_emotion(text)
        logger.info(f"[KajalTTS] Synthesizing | emotion={emotion} | '{text[:60]}...'")

        url = f"{self._base_url}/v1/text-to-speech"
        payload = {
            "text": text,
            "voice": self._voice,
            "emotion": emotion,
            "language": self._language,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if chunk:
                            await self.push_frame(
                                TTSAudioRawFrame(
                                    audio=chunk,
                                    sample_rate=24000,
                                    num_channels=1,
                                )
                            )
        except httpx.HTTPError as e:
            logger.error(f"[KajalTTS] HTTP error: {e}")
        except asyncio.CancelledError:
            logger.info("[KajalTTS] Synthesis cancelled (user interrupted)")
            raise
