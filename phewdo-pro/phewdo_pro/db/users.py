"""User/client lookups and cookie management."""
from __future__ import annotations

import logging
from typing import Optional

from phewdo_pro.supabase_client import get_client

logger = logging.getLogger(__name__)


def get_active_users() -> list[dict]:
    """Get all active PhewDo users with their client_id.

    Returns:
        List of user dicts from phewdo_users where status='active'.
    """
    client = get_client()
    result = (
        client.table("phewdo_users")
        .select("id, email, client_id, daily_limit, max_campaigns, plan")
        .eq("status", "active")
        .execute()
    )
    return result.data or []


def get_user_campaigns(user_id: str, client_id: str = "") -> list[dict]:
    """Get active campaigns for a user.

    Returns:
        List of campaign dicts from phewdo_campaigns.
    """
    client = get_client()
    result = (
        client.table("phewdo_campaigns")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .execute()
    )
    # Fallback: try by client_id
    if not result.data and client_id:
        result = (
            client.table("phewdo_campaigns")
            .select("*")
            .eq("client_id", client_id)
            .eq("status", "active")
            .execute()
        )
    return result.data or []


def get_client_cookies(client_id: str) -> Optional[dict]:
    """Get LinkedIn cookies for a client from the clients table.

    Existing DB column names: linkedin_li_at, linkedin_jsessionid, etc.

    Returns:
        Dict with 'li_at', 'jsessionid', 'email', 'password', 'user_country' keys, or None.
    """
    client = get_client()
    result = (
        client.table("clients")
        .select("linkedin_li_at, linkedin_jsessionid, linkedin_email, linkedin_password, user_country, linkedin_email_app_password")
        .eq("id", client_id)
        .single()
        .execute()
    )

    if not result.data:
        return None

    data = result.data
    return {
        "li_at": data.get("linkedin_li_at", ""),
        "jsessionid": data.get("linkedin_jsessionid", ""),
        "email": data.get("linkedin_email", ""),
        "password": data.get("linkedin_password", ""),
        "user_country": data.get("user_country", "IN"),
        "email_app_password": data.get("linkedin_email_app_password", ""),
    }


def update_client_cookies(
    client_id: str, li_at: str, jsessionid: str
) -> None:
    """Update LinkedIn cookies for a client after re-authentication."""
    client = get_client()
    client.table("clients").update({
        "linkedin_li_at": li_at,
        "linkedin_jsessionid": jsessionid,
        "linkedin_cookie_health": "ok",
    }).eq("id", client_id).execute()
    logger.info("Updated cookies for client %s", client_id)


def get_user_daily_limit(user_id: str) -> int:
    """Get the daily connection limit for a user.

    Falls back to config default if not set on user record.
    """
    from phewdo_pro.config import DAILY_CONNECT_LIMIT

    client = get_client()
    result = (
        client.table("phewdo_users")
        .select("daily_limit")
        .eq("id", user_id)
        .single()
        .execute()
    )

    if result.data and result.data.get("daily_limit"):
        return result.data["daily_limit"]
    return DAILY_CONNECT_LIMIT
