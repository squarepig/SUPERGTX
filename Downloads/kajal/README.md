# Kajal — DueDoor AI Voice Engine

Low-latency AI calling system for DueDoor real estate platform.  
Built on: **Twilio → Pipecat → Claude API → Svara-TTS + Faster-Whisper on RunPod**

---

## Architecture

```
Twilio (Phone)
     │
     ▼
Pipecat Orchestrator  ◄──► Anthropic Claude API
     │         │
     ▼         ▼
Whisper STT   Svara TTS
(RunPod)     (RunPod GPU)
     │         │
     ▼         ▼
        Supabase
      (Lead Context)
```

## Pods

| Pod | Role | GPU |
|-----|------|-----|
| `svara-tts` | Text → Speech (Kajal's voice) | RTX 4090 / A6000 |
| `whisper-stt` | Speech → Text | RTX 3090 / A4000 |
| `orchestrator` | Pipecat glue + Claude API | CPU Pod |

## Quick Start

```bash
# 1. Deploy TTS pod
cd svara-tts && docker build -t kajal-svara .

# 2. Deploy STT pod
cd whisper-stt && docker build -t kajal-whisper .

# 3. Start orchestrator
cd orchestrator && pip install -r requirements.txt && python bot.py
```

## Environment Variables

See `.env.example` in each subdirectory.

## Languages Supported

Kajal (Svara-TTS) supports 19 Indic languages including Hindi, Tamil, Telugu, Kannada, Malayalam — perfect for Hinglish/Kanglish code-switching common in Indian real estate calls.
