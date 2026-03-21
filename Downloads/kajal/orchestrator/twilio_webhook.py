"""
twilio_webhook.py — HTTP webhook server for Twilio call events
Receives incoming call webhooks from Twilio and spins up a Kajal bot per call.

Set your Twilio phone number's Voice webhook to:
  POST https://your-orchestrator-url/incoming-call
"""

import os
import asyncio
from loguru import logger
from aiohttp import web
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

from bot import run_kajal_bot

PORT = int(os.getenv("WEBHOOK_PORT", 8080))
PUBLIC_URL = os.getenv("PUBLIC_URL", "")   # e.g. https://xyz.runpod.net


# ---------------------------------------------------------------------------
# Webhook: Twilio calls this when a new call arrives
# ---------------------------------------------------------------------------
async def handle_incoming_call(request: web.Request) -> web.Response:
    data = await request.post()
    call_sid    = data.get("CallSid", "unknown")
    from_number = data.get("From", "")
    to_number   = data.get("To", "")

    logger.info(f"[Webhook] Incoming call | sid={call_sid} | from={from_number} | to={to_number}")

    # TwiML: connect Twilio media stream to our WebSocket
    response = VoiceResponse()
    connect  = Connect()
    stream   = Stream(url=f"wss://{PUBLIC_URL}/media-stream/{call_sid}")
    connect.append(stream)
    response.append(connect)

    # Fire off the Kajal bot in the background
    asyncio.create_task(run_kajal_bot(call_sid, from_number))

    return web.Response(
        text=str(response),
        content_type="application/xml",
    )


# ---------------------------------------------------------------------------
# Webhook: Twilio calls this when a call ends (status callback)
# ---------------------------------------------------------------------------
async def handle_call_status(request: web.Request) -> web.Response:
    data = await request.post()
    call_sid     = data.get("CallSid", "unknown")
    call_status  = data.get("CallStatus", "unknown")
    duration     = data.get("CallDuration", "0")

    logger.info(f"[Webhook] Call status | sid={call_sid} | status={call_status} | duration={duration}s")
    return web.Response(text="OK")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "kajal-orchestrator"})


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/incoming-call",  handle_incoming_call)
    app.router.add_post("/call-status",    handle_call_status)
    app.router.add_get("/health",          health)
    return app


if __name__ == "__main__":
    logger.info(f"Starting Kajal webhook server on port {PORT}...")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
