"""Dispatcher — poll loop, claim tasks, execute handlers.

Compatible with existing phewdo_task_queue schema where tasks carry
user_id and client_id directly. Creates VoyagerAPIClient per client_id
with cookie auth (primary) and credential login (fallback).
"""
from __future__ import annotations

import logging
import signal
import time
import traceback
from typing import Optional

from phewdo_pro.api.client import VoyagerAPIClient
from phewdo_pro.config import (
    ALLOWED_USER_IDS,
    HEAL_INTERVAL_SECONDS,
    POLL_INTERVAL,
    WORKER_ID,
)
from phewdo_pro.db.tasks import (
    claim_next_task,
    complete_task,
    fail_task,
    heal_stale_tasks,
    seed_tasks_for_user,
)
from phewdo_pro.db.users import (
    get_active_users,
    get_client_cookies,
    get_user_campaigns,
    get_user_daily_limit,
    update_client_cookies,
)
from phewdo_pro.exceptions import AuthenticationError, CookieExpired
from phewdo_pro.tasks.registry import get_handler

logger = logging.getLogger(__name__)


class Dispatcher:
    """Main daemon dispatcher — runs the poll loop."""

    def __init__(self):
        self._running = False
        self._api_clients: dict[str, VoyagerAPIClient] = {}
        self._failed_clients: dict[str, float] = {}  # client_id -> timestamp of last failure
        self._last_heal = 0.0
        self._last_seed = 0.0

    def start(self) -> None:
        """Start the polling loop. Blocks until shutdown."""
        self._running = True
        self._setup_signal_handlers()

        logger.info("Dispatcher starting (worker=%s)", WORKER_ID)

        # Initial seed
        self._seed_all_users()

        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt — shutting down")
                self._running = False
            except Exception as e:
                logger.error(
                    "Unhandled error in dispatcher: %s\n%s",
                    e,
                    traceback.format_exc(),
                )
                time.sleep(POLL_INTERVAL)

        logger.info("Dispatcher stopped")

    def stop(self) -> None:
        self._running = False

    def _setup_signal_handlers(self) -> None:
        def handler(signum, frame):
            signame = signal.Signals(signum).name
            logger.info("Received %s — shutting down gracefully", signame)
            self._running = False

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def _tick(self) -> None:
        """One iteration of the poll loop."""
        now = time.time()

        # Periodic heal
        if now - self._last_heal > HEAL_INTERVAL_SECONDS:
            healed = heal_stale_tasks()
            if healed:
                logger.info("Healed %d stale tasks", healed)
            self._last_heal = now

        # Periodic re-seed (every 30 minutes)
        if now - self._last_seed > 1800:
            self._seed_all_users()
            self._last_seed = now

        # Claim and execute a task
        task = claim_next_task()
        if task is None:
            time.sleep(POLL_INTERVAL)
            return

        task_id = task["id"]
        task_type = task.get("task_type", "")
        user_id = task.get("user_id", "")
        client_id = task.get("client_id", "")
        payload = task.get("payload") or {}

        logger.info(
            "Claimed task #%d: %s (user=%s)",
            task_id, task_type, user_id,
        )

        # Skip tasks for users not in allowed list
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            fail_task(task_id, f"User {user_id} not in ALLOWED_USER_IDS — skipping")
            return

        # Get handler
        handler = get_handler(task_type)
        if handler is None:
            fail_task(task_id, f"Unknown task type: {task_type}")
            return

        # Build context from task (tasks carry user_id, client_id directly)
        daily_limit = get_user_daily_limit(user_id) if user_id else 20
        context = {
            "user_id": user_id,
            "client_id": client_id,
            "daily_limit": daily_limit,
            "campaign_id": payload.get("campaign_id", ""),
            "campaign": self._get_campaign(payload.get("campaign_id", "")),
        }

        # Skip clients with recently failed auth (retry every 30 min)
        if client_id in self._failed_clients:
            if time.time() - self._failed_clients[client_id] < 1800:
                fail_task(task_id, "Client auth recently failed — waiting for fresh cookies")
                return
            else:
                del self._failed_clients[client_id]

        # Get or create API client
        try:
            api_client = self._get_api_client(client_id)
        except (CookieExpired, AuthenticationError) as e:
            fail_task(task_id, f"Auth failed: {e}")
            self._api_clients.pop(client_id, None)
            self._failed_clients[client_id] = time.time()
            # Mark cookie health as expired in DB
            try:
                from phewdo_pro.supabase_client import get_client as get_sb
                get_sb().table("clients").update(
                    {"linkedin_cookie_health": "expired"}
                ).eq("id", client_id).execute()
            except Exception:
                pass
            return
        except Exception as e:
            fail_task(task_id, f"API client creation failed: {e}")
            return

        # Execute handler
        try:
            handler(task, api_client, context)
            complete_task(task_id)
            logger.info("Task #%d completed", task_id)
        except CookieExpired as e:
            logger.error("Cookie expired during task #%d: %s", task_id, e)
            # Evict stale client
            self._api_clients.pop(client_id, None)
            # Attempt credential re-login before giving up
            refreshed = self._try_credential_refresh(client_id)
            if refreshed:
                logger.info("Credential refresh succeeded for client %s — retrying task", client_id)
                try:
                    new_client = self._api_clients[client_id]
                    handler(task, new_client, context)
                    complete_task(task_id)
                    logger.info("Task #%d completed after credential refresh", task_id)
                    return
                except (CookieExpired, AuthenticationError) as e2:
                    logger.error("Retry also failed after credential refresh: %s", e2)
                    self._api_clients.pop(client_id, None)

            fail_task(task_id, f"Cookie expired: {e}")
            self._failed_clients[client_id] = time.time()
            try:
                from phewdo_pro.supabase_client import get_client as get_sb
                get_sb().table("clients").update(
                    {"linkedin_cookie_health": "expired"}
                ).eq("id", client_id).execute()
            except Exception:
                pass
        except Exception as e:
            logger.error(
                "Task #%d failed: %s\n%s",
                task_id, e, traceback.format_exc(),
            )
            fail_task(task_id, f"{type(e).__name__}: {str(e)[:500]}")

    def _get_campaign(self, campaign_id: str) -> dict:
        """Look up campaign from DB."""
        if not campaign_id:
            return {}
        try:
            from phewdo_pro.supabase_client import get_client
            client = get_client()
            result = (
                client.table("phewdo_campaigns")
                .select("*")
                .eq("id", campaign_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else {}
        except Exception:
            return {}

    def _get_api_client(self, client_id: str) -> VoyagerAPIClient:
        """Get or create a VoyagerAPIClient for the given client_id.

        Reuses sessions per client_id. Falls back to credential login
        if cookies are expired.
        """
        if not client_id:
            raise AuthenticationError("No client_id provided")

        # Reuse existing client if cached
        if client_id in self._api_clients:
            return self._api_clients[client_id]

        # Load cookies from DB
        cookies = get_client_cookies(client_id)
        if not cookies:
            raise AuthenticationError(f"No cookies found for client {client_id}")

        li_at = cookies.get("li_at", "")
        jsessionid = cookies.get("jsessionid", "")
        user_country = cookies.get("user_country", "IN")

        email = cookies.get("email", "")
        password = cookies.get("password", "")

        if li_at and jsessionid:
            api_client = VoyagerAPIClient.from_cookies(
                li_at=li_at,
                jsessionid=jsessionid,
                country_code=user_country,
            )
            # Skip verify_session — handle auth errors in actual API calls
            self._api_clients[client_id] = api_client
            logger.info("API client created for client %s (cookie auth, country=%s)", client_id, user_country)
            return api_client

        # No cookies — try credential login directly
        if not email or not password:
            raise CookieExpired(
                f"No cookies and no credentials for client {client_id}"
            )

        email_app_pw = cookies.get("email_app_password", "")
        logger.info("No cookies for client %s — attempting credential login", client_id)
        api_client = VoyagerAPIClient.from_credentials(
            email=email,
            password=password,
            country_code=user_country,
            email_app_password=email_app_pw,
        )

        # Save new cookies back to DB
        update_client_cookies(client_id, api_client.li_at, api_client.jsessionid)

        self._api_clients[client_id] = api_client
        logger.info("API client created for client %s (credential login)", client_id)
        return api_client

    def _try_credential_refresh(self, client_id: str) -> bool:
        """Try to re-authenticate using stored email/password.

        On success, caches the new API client and updates cookies in DB.
        Returns True if credential login succeeded.
        """
        try:
            cookies = get_client_cookies(client_id)
            if not cookies:
                return False

            email = cookies.get("email", "")
            password = cookies.get("password", "")
            country = cookies.get("user_country", "US")
            email_app_pw = cookies.get("email_app_password", "")

            if not email or not password:
                logger.warning("No credentials stored for client %s — cannot refresh", client_id)
                return False

            logger.info("Attempting credential refresh for client %s (%s)", client_id, email)
            api_client = VoyagerAPIClient.from_credentials(
                email=email,
                password=password,
                country_code=country,
                email_app_password=email_app_pw,
            )

            # Save new cookies to DB
            update_client_cookies(client_id, api_client.li_at, api_client.jsessionid)

            # Cache the new client
            self._api_clients[client_id] = api_client
            # Clear failure tracking
            self._failed_clients.pop(client_id, None)

            logger.info("Credential refresh succeeded for client %s", client_id)
            return True

        except (AuthenticationError, CookieExpired) as e:
            logger.warning("Credential refresh failed for client %s: %s", client_id, e)
            return False
        except Exception as e:
            logger.error("Credential refresh error for client %s: %s", client_id, e)
            return False

    def _seed_all_users(self) -> None:
        """Seed task chains for allowed active users."""
        try:
            users = get_active_users()
            if ALLOWED_USER_IDS:
                users = [u for u in users if u["id"] in ALLOWED_USER_IDS]
            for user in users:
                user_id = user["id"]
                client_id = user.get("client_id", "")
                campaigns = get_user_campaigns(user_id, client_id)
                if campaigns:
                    seed_tasks_for_user(user_id, client_id, campaigns)

            logger.info("Re-seeded tasks for %d active users", len(users))
        except Exception as e:
            logger.error("Failed to seed tasks: %s", e, exc_info=True)
