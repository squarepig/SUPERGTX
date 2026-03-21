"""
bot.py — Kajal Pipecat Orchestrator
DueDoor AI Voice Engine

Pipeline:
  Twilio (phone audio)
    → SileroVAD (interruption detection)
    → Faster-Whisper STT (RunPod)
    → Context Aggregator (conversation memory)
    → Claude API (streamed LLM response)
    → Svara TTS (RunPod GPU)
    → Twilio (voice output)
    → Supabase (lead logging)

Audio: 16kHz mono PCM throughout
"""

import os
import asyncio
from dotenv import load_dotenv
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.anthropic import AnthropicLLMService
from pipecat.transports.services.twilio import TwilioTransport, TwilioParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.aggregators.llm_response import LLMAssistantResponseAggregator, LLMUserResponseAggregator

from kajal_stt import KajalWhisperSTTService
from kajal_tts import KajalSvaraTTSService
from kajal_system_prompt import build_system_prompt
from supabase_helper import get_lead_context, log_call_event

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN  = os.environ["TWILIO_AUTH_TOKEN"]
WHISPER_WS_URL     = os.environ["WHISPER_WS_URL"]      # ws://runpod-whisper-ip:8001
SVARA_HTTP_URL     = os.environ["SVARA_HTTP_URL"]       # http://runpod-svara-ip:8000

# ---------------------------------------------------------------------------
# Main bot runner — called per incoming Twilio call
# ---------------------------------------------------------------------------
async def run_kajal_bot(call_sid: str, lead_phone: str):
    logger.info(f"[Kajal] Starting call bot | call_sid={call_sid} | phone={lead_phone}")

    # 1. Fetch lead context from Supabase (only the columns we need)
    lead = await get_lead_context(lead_phone)
    logger.info(f"[Kajal] Lead context: {lead}")

    # 2. Build Kajal's system prompt with lead context injected
    system_prompt = build_system_prompt(lead)

    # 3. Twilio transport — handles real-time audio I/O
    transport = TwilioTransport(
        account_sid=TWILIO_ACCOUNT_SID,
        auth_token=TWILIO_AUTH_TOKEN,
        params=TwilioParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            vad_analyzer=SileroVADAnalyzer(),   # detects interruptions
        ),
    )

    # 4. STT — Kajal Faster-Whisper on RunPod
    stt = KajalWhisperSTTService(ws_url=WHISPER_WS_URL)

    # 5. LLM — Claude via Anthropic API (streamed)
    llm = AnthropicLLMService(
        api_key=ANTHROPIC_API_KEY,
        model="claude-sonnet-4-20250514",
        stream=True,
    )

    # 6. TTS — Kajal Svara on RunPod GPU
    tts = KajalSvaraTTSService(
        base_url=SVARA_HTTP_URL,
        voice="kajal",
        language="hi-en",        # Hinglish default
    )

    # 7. Conversation context
    context = OpenAILLMContext(
        messages=[{"role": "system", "content": system_prompt}]
    )
    context_aggregator = llm.create_context_aggregator(context)

    # 8. Build pipeline
    pipeline = Pipeline([
        transport.input(),              # Audio in from Twilio
        stt,                            # Speech → Text (Whisper RunPod)
        context_aggregator.user(),      # Aggregate user turn
        llm,                            # Claude (streamed)
        tts,                            # Text → Speech (Svara RunPod)
        transport.output(),             # Audio out to Twilio
        context_aggregator.assistant(), # Aggregate assistant turn
    ])

    # 9. Run pipeline
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,       # Silero VAD handles this
            enable_metrics=True,
            report_only_initial_ttfb=True,
        ),
    )

    @transport.event_handler("on_call_ended")
    async def on_call_ended(transport, call_sid):
        logger.info(f"[Kajal] Call ended: {call_sid}")
        await log_call_event(call_sid, lead_phone, "ended", context.messages)
        await task.cancel()

    runner = PipelineRunner()
    await runner.run(task)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    call_sid   = sys.argv[1] if len(sys.argv) > 1 else "test_call"
    lead_phone = sys.argv[2] if len(sys.argv) > 2 else "+919999999999"
    asyncio.run(run_kajal_bot(call_sid, lead_phone))
