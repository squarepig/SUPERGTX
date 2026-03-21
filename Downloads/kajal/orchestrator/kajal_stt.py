"""
kajal_stt.py — Pipecat STT service wrapping Kajal's Faster-Whisper RunPod pod
"""

import json
import asyncio
import websockets
import numpy as np
from loguru import logger
from pipecat.services.ai_services import STTService
from pipecat.frames.frames import TranscriptionFrame, AudioRawFrame


class KajalWhisperSTTService(STTService):
    """
    Streams audio to the Kajal Faster-Whisper WebSocket pod on RunPod
    and returns TranscriptionFrames to the Pipecat pipeline.
    """

    def __init__(self, ws_url: str, **kwargs):
        super().__init__(**kwargs)
        self._ws_url = ws_url
        self._ws = None
        self._receive_task = None

    async def start(self, frame):
        await super().start(frame)
        logger.info(f"[KajalSTT] Connecting to Whisper pod: {self._ws_url}")
        self._ws = await websockets.connect(self._ws_url, max_size=10 * 1024 * 1024)
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("[KajalSTT] Connected ✓")

    async def stop(self, frame):
        if self._receive_task:
            self._receive_task.cancel()
        if self._ws:
            await self._ws.close()
        await super().stop(frame)

    async def run_stt(self, audio: AudioRawFrame) -> None:
        """Send raw PCM audio bytes to the Whisper WebSocket."""
        if self._ws and not self._ws.closed:
            await self._ws.send(audio.audio)

    async def _receive_loop(self):
        """Listen for transcription results from the Whisper pod."""
        try:
            async for message in self._ws:
                data = json.loads(message)
                if data.get("type") == "transcript" and data.get("text"):
                    text = data["text"].strip()
                    lang = data.get("language", "hi")
                    logger.info(f"[KajalSTT] → '{text}' (lang={lang})")
                    await self.push_frame(TranscriptionFrame(text=text, user_id="lead", timestamp=""))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("[KajalSTT] WebSocket closed")
        except asyncio.CancelledError:
            pass
