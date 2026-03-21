"""
supabase_helper.py — DueDoor Supabase integration for Kajal
Fetches ONLY the columns needed for the current call — no massive JSON blobs.
Logs call events for CRM tracking.
"""

import os
import asyncio
from typing import Optional
from loguru import logger
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# Global singleton client
_client: Optional[Client] = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


async def get_lead_context(phone: str) -> dict:
    """
    Fetch only the columns Kajal needs for the call.
    Avoids pulling large JSON blobs that cause truncation.
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: get_client()
                .from_("leads")
                .select(
                    "id, name, phone, property_interest, budget, "
                    "location_preference, language_preference, "
                    "agent_name, project_name, status"
                )
                .eq("phone", phone)
                .limit(1)
                .execute()
        )

        if result.data and len(result.data) > 0:
            lead = result.data[0]
            logger.info(f"[Supabase] Lead found: {lead.get('name', 'Unknown')} | status={lead.get('status')}")
            return lead
        else:
            logger.warning(f"[Supabase] No lead found for phone: {phone}")
            return {}

    except Exception as e:
        logger.error(f"[Supabase] get_lead_context error: {e}")
        return {}


async def log_call_event(
    call_sid: str,
    phone: str,
    event_type: str,
    messages: list = None
) -> None:
    """
    Log call events to Supabase for CRM tracking.
    event_type: 'started' | 'ended' | 'transferred' | 'site_visit_booked'
    """
    try:
        # Build transcript summary from messages
        transcript = None
        if messages:
            lines = []
            for m in messages:
                role = m.get("role", "")
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                if role in ("user", "assistant") and content:
                    label = "Lead" if role == "user" else "Kajal"
                    lines.append(f"{label}: {content}")
            transcript = "\n".join(lines)

        payload = {
            "call_sid": call_sid,
            "phone": phone,
            "event_type": event_type,
            "transcript": transcript,
            "source": "kajal_voice",
        }

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: get_client()
                .from_("call_logs")
                .insert(payload)
                .execute()
        )
        logger.info(f"[Supabase] Call event logged: {event_type} | {call_sid}")

    except Exception as e:
        logger.error(f"[Supabase] log_call_event error: {e}")


async def update_lead_status(phone: str, status: str, notes: str = None) -> None:
    """
    Update lead status after call completes.
    status: 'called' | 'interested' | 'not_interested' | 'site_visit_booked' | 'follow_up'
    """
    try:
        update_data = {"status": status, "last_called_by": "kajal"}
        if notes:
            update_data["kajal_notes"] = notes

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: get_client()
                .from_("leads")
                .update(update_data)
                .eq("phone", phone)
                .execute()
        )
        logger.info(f"[Supabase] Lead status updated: {phone} → {status}")

    except Exception as e:
        logger.error(f"[Supabase] update_lead_status error: {e}")
