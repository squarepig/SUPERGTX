"""VoyagerAPIClient — Pure HTTP client for LinkedIn's Voyager API.

Replaces Playwright browser-based fetch with direct requests.Session calls.
Supports cookie auth (primary) and credential login (fallback).
"""
from __future__ import annotations

import base64
import json
import logging
import random
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from phewdo_pro.api.voyager import (
    parse_linkedin_voyager_response,
    parse_connection_degree,
)
from phewdo_pro.config import (
    MIN_ACTION_DELAY,
    MAX_ACTION_DELAY,
    NSOCKS_USERNAME,
    NSOCKS_PASSWORD,
    NSOCKS_GATEWAY,
    NSOCKS_PORT,
    NSOCKS_SESSION_LIFE,
)
from phewdo_pro.exceptions import (
    AuthenticationError,
    CookieExpired,
    RateLimited,
    SkipProfile,
)

logger = logging.getLogger(__name__)


def _generate_tracking_id() -> str:
    """Generate a random tracking ID for connection requests."""
    return base64.b64encode(
        bytearray([random.randrange(256) for _ in range(16)])
    ).decode()


def _build_proxy_url(country_code: str = "US") -> str:
    """Build NSocks residential proxy URL."""
    if not NSOCKS_USERNAME or not NSOCKS_PASSWORD:
        return ""
    session_id = random.randint(100000, 999999)
    return (
        f"http://{NSOCKS_USERNAME}"
        f"_area-{country_code}"
        f"_session-{session_id}"
        f"_life-{NSOCKS_SESSION_LIFE}"
        f":{NSOCKS_PASSWORD}"
        f"@{NSOCKS_GATEWAY}:{NSOCKS_PORT}"
    )


class VoyagerAPIClient:
    """Pure HTTP client for LinkedIn's Voyager API."""

    BASE_URL = "https://www.linkedin.com"
    API_BASE = "https://www.linkedin.com/voyager/api"
    AUTH_URL = "https://www.linkedin.com/uas/authenticate"

    HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        ),
        "accept-language": "en-AU,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
        "accept": "application/vnd.linkedin.normalized+json+2.1",
    }

    MOBILE_USER_AGENT = "LinkedIn/8.8.1 CFNetwork/711.3.18 Darwin/14.0.0"

    TOPCARD_DECORATION = (
        "com.linkedin.voyager.dash.deco.identity.profile."
        "TopCardSupplementary-120"
    )

    FULL_PROFILE_DECORATION = (
        "com.linkedin.voyager.dash.deco.identity.profile."
        "FullProfileWithEntities-91"
    )

    def __init__(
        self,
        li_at: str,
        jsessionid: str,
        country_code: str = "US",
        use_proxy: bool = True,
    ):
        """Initialize with LinkedIn cookies.

        Args:
            li_at: LinkedIn authentication cookie value.
            jsessionid: JSESSIONID cookie value (with or without quotes).
            country_code: Country code for proxy routing.
            use_proxy: Whether to use NSocks proxy.
        """
        self.li_at = li_at
        self.jsessionid = jsessionid.strip('"')
        self.session = requests.Session()
        self.session.max_redirects = 10

        # Set default headers
        self.session.headers.update(self.HEADERS)
        self.session.headers["csrf-token"] = self.jsessionid

        # Set Cookie header directly — requests.Session cookie jar has delivery issues
        self._cookie_header = f'li_at={self.li_at}; JSESSIONID="{self.jsessionid}"'

        # Configure proxy
        if use_proxy:
            proxy_url = _build_proxy_url(country_code)
            if proxy_url:
                self.session.proxies = {
                    "http": proxy_url,
                    "https": proxy_url,
                }
                logger.info("Proxy configured for country=%s", country_code)

        # Request timeout (seconds)
        self.timeout = 30

    # ── Anti-detection ────────────────────────────────────────────

    @staticmethod
    def default_evade():
        """Random delay between actions to mimic human behavior."""
        delay = random.uniform(MIN_ACTION_DELAY, MAX_ACTION_DELAY)
        logger.debug("Evade delay: %.1fs", delay)
        time.sleep(delay)

    # ── Low-level transport ───────────────────────────────────────

    def _get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> requests.Response:
        """GET request with error handling."""
        h = {**self.session.headers, **(headers or {})}
        h["Cookie"] = self._cookie_header
        resp = requests.get(
            url, params=params, headers=h, proxies=self.session.proxies,
            timeout=self.timeout, allow_redirects=False,
        )
        self._check_response(resp)
        return resp

    def _post(
        self,
        url: str,
        data: dict | str | None = None,
        headers: dict | None = None,
    ) -> requests.Response:
        """POST request with error handling."""
        h = {**self.session.headers, **(headers or {})}
        h["Cookie"] = self._cookie_header
        if isinstance(data, dict):
            h.setdefault("content-type", "application/json")
            resp = requests.post(
                url, json=data, headers=h, proxies=self.session.proxies,
                timeout=self.timeout, allow_redirects=False,
            )
        else:
            resp = requests.post(
                url, data=data, headers=h, proxies=self.session.proxies,
                timeout=self.timeout, allow_redirects=False,
            )
        self._check_response(resp)
        return resp

    def _check_response(self, resp: requests.Response) -> None:
        """Check response for auth/rate-limit errors."""
        if resp.status_code in (301, 302, 303, 307):
            sc = resp.headers.get("Set-Cookie", "")
            if "delete" in sc:
                raise CookieExpired("LinkedIn revoked session (delete cookie)")
            raise CookieExpired(f"LinkedIn returned {resp.status_code} redirect")
        if resp.status_code == 401:
            raise CookieExpired("LinkedIn returned 401 — cookie expired")
        if resp.status_code == 403:
            # Check if it's a CSRF/session failure vs normal profile restriction
            body = resp.text[:500].lower()
            if "csrf" in body or "session" in body or "unauthorized" in body:
                raise CookieExpired(f"LinkedIn CSRF/session check failed (403)")
        if resp.status_code == 429:
            raise RateLimited("LinkedIn returned 429 — too many requests")

    # ── Authentication ────────────────────────────────────────────

    @classmethod
    def from_cookies(
        cls,
        li_at: str,
        jsessionid: str,
        country_code: str = "US",
        use_proxy: bool = True,
    ) -> VoyagerAPIClient:
        """Create client from existing cookies (primary auth mode)."""
        return cls(
            li_at=li_at,
            jsessionid=jsessionid,
            country_code=country_code,
            use_proxy=use_proxy,
        )

    @classmethod
    def from_credentials(
        cls,
        email: str,
        password: str,
        country_code: str = "US",
        use_proxy: bool = True,
        max_proxy_retries: int = 3,
        email_app_password: str = "",
    ) -> VoyagerAPIClient:
        """Create client by logging in with email/password (fallback).

        Uses mobile User-Agent for the auth request, then switches to
        desktop UA for subsequent API calls. Retries with different proxy
        sessions if the first attempt gets a non-JSON/403 response.
        """
        last_error = None
        for attempt in range(max_proxy_retries):
            try:
                return cls._attempt_credential_login(
                    email, password, country_code, use_proxy,
                    email_app_password=email_app_password,
                )
            except AuthenticationError as e:
                last_error = e
                err_msg = str(e)
                # Retry with new proxy session on 403/empty/SSL errors
                if any(kw in err_msg for kw in ("403", "not JSON", "SSL", "EOF")):
                    logger.warning(
                        "Credential login attempt %d/%d failed: %s — retrying with new proxy",
                        attempt + 1, max_proxy_retries, err_msg[:100],
                    )
                    time.sleep(2)
                    continue
                # Don't retry on CHALLENGE or PASS-related errors
                raise
        raise last_error  # type: ignore[misc]

    @classmethod
    def _attempt_credential_login(
        cls,
        email: str,
        password: str,
        country_code: str = "US",
        use_proxy: bool = True,
        email_app_password: str = "",
    ) -> VoyagerAPIClient:
        """Single attempt at credential login."""
        # Step 1: Get login page to obtain JSESSIONID
        init_session = requests.Session()
        init_session.max_redirects = 5

        # Use proxy for auth too (VPS IP may be blocked)
        if use_proxy:
            proxy_url = _build_proxy_url(country_code)
            if proxy_url:
                init_session.proxies = {"http": proxy_url, "https": proxy_url}

        # Use realistic browser headers for the login flow
        init_session.headers.update({
            "user-agent": cls.HEADERS["user-agent"],
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "accept-encoding": "gzip, deflate, br",
        })

        resp = init_session.get(
            "https://www.linkedin.com/uas/authenticate",
            timeout=30,
        )
        logger.debug("Auth GET status=%d, cookies=%s", resp.status_code, list(init_session.cookies.keys()))

        cookies = init_session.cookies.get_dict()
        jsessionid = cookies.get("JSESSIONID", "").strip('"')

        if not jsessionid:
            # Try login page as fallback
            resp = init_session.get("https://www.linkedin.com/login", timeout=30)
            cookies = init_session.cookies.get_dict()
            jsessionid = cookies.get("JSESSIONID", "").strip('"')

        if not jsessionid:
            raise AuthenticationError(
                "Failed to obtain JSESSIONID from LinkedIn"
            )

        # Step 2: Authenticate with mobile UA (better success rate)
        auth_data = urlencode({
            "session_key": email,
            "session_password": password,
            "JSESSIONID": jsessionid,
        })
        auth_headers = {
            "user-agent": cls.MOBILE_USER_AGENT,
            "content-type": "application/x-www-form-urlencoded",
            "csrf-token": jsessionid,
            "x-li-user-agent": "LIAuthLibrary:0.0.3 com.linkedin.android:4.1.881 Asus_ASUS_Z01QD:android_9",
        }
        init_session.cookies.set(
            "JSESSIONID", f'"{jsessionid}"', domain=".linkedin.com"
        )

        resp = init_session.post(
            cls.AUTH_URL,
            data=auth_data,
            headers=auth_headers,
            timeout=30,
            allow_redirects=False,
        )

        logger.debug(
            "Auth POST status=%d, content-type=%s, body_len=%d",
            resp.status_code, resp.headers.get("content-type", ""), len(resp.text),
        )

        try:
            result = resp.json()
        except Exception:
            raise AuthenticationError(
                f"Auth response not JSON (HTTP {resp.status_code}): {resp.text[:200]}"
            )

        login_result = result.get("login_result", "UNKNOWN")
        logger.info("Credential login result: %s for %s", login_result, email)

        if login_result == "CHALLENGE":
            # HTTP can't handle CHALLENGE (needs JS execution)
            # Fall back to Playwright headless browser login
            logger.info(
                "CHALLENGE detected for %s — falling back to Playwright browser login",
                email,
            )
            return cls._playwright_credential_login(
                email, password, country_code, use_proxy,
                email_app_password=email_app_password,
            )

        elif login_result != "PASS":
            raise AuthenticationError(
                f"Login failed: {login_result}"
            )

        # Step 3: Extract li_at from cookies
        li_at = init_session.cookies.get("li_at")
        if not li_at:
            raise AuthenticationError(
                "Login succeeded but li_at cookie not found"
            )

        logger.info("Credential login successful for %s", email)
        return cls(
            li_at=li_at,
            jsessionid=jsessionid,
            country_code=country_code,
            use_proxy=use_proxy,
        )

    @classmethod
    def _playwright_credential_login(
        cls,
        email: str,
        password: str,
        country_code: str = "US",
        use_proxy: bool = True,
        timeout_ms: int = 60000,
        email_app_password: str = "",
    ) -> VoyagerAPIClient:
        """Login via headless Playwright browser — handles CHALLENGE automatically.

        If LinkedIn requires PIN verification and email_app_password is provided,
        reads the PIN from Gmail via IMAP and auto-submits it.
        After login, extracts li_at + JSESSIONID cookies and returns an HTTP client.
        """
        from playwright.sync_api import sync_playwright

        logger.info("Playwright login starting for %s", email)
        pw = None
        browser = None

        try:
            pw = sync_playwright().start()

            # Build launch args
            launch_args = ["--disable-blink-features=AutomationControlled"]

            # Proxy config for the browser — Playwright needs server/username/password split
            proxy_cfg = None
            if use_proxy and NSOCKS_USERNAME and NSOCKS_PASSWORD:
                session_id = random.randint(100000, 999999)
                proxy_cfg = {
                    "server": f"http://{NSOCKS_GATEWAY}:{NSOCKS_PORT}",
                    "username": (
                        f"{NSOCKS_USERNAME}"
                        f"_area-{country_code}"
                        f"_session-{session_id}"
                        f"_life-{NSOCKS_SESSION_LIFE}"
                    ),
                    "password": NSOCKS_PASSWORD,
                }

            browser = pw.chromium.launch(
                headless=True,
                args=launch_args,
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/134.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                proxy=proxy_cfg,
            )
            context.set_default_timeout(timeout_ms)

            # Stealth: remove webdriver flag
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            page = context.new_page()

            # Step 1: Go to login page
            logger.debug("Playwright: navigating to login page")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            page.wait_for_selector('input#username', state="visible", timeout=15000)

            # Step 2: Type credentials with human-like delays
            email_input = page.locator('input#username')
            email_input.click()
            email_input.fill("")  # clear first
            for char in email:
                email_input.type(char, delay=random.randint(30, 80))

            time.sleep(random.uniform(0.3, 0.8))

            pw_input = page.locator('input#password')
            pw_input.click()
            pw_input.fill("")
            for char in password:
                pw_input.type(char, delay=random.randint(30, 80))

            time.sleep(random.uniform(0.3, 0.8))

            # Step 3: Click submit and wait for navigation
            logger.debug("Playwright: submitting login form")
            page.locator('button[type="submit"]').click()

            # Wait for redirect to /feed or /mynetwork (login success)
            # or stay on challenge page (browser auto-resolves JS challenges)
            try:
                page.wait_for_url(
                    "**/feed**",
                    timeout=timeout_ms,
                )
                logger.info("Playwright: redirected to feed — login success")
            except Exception:
                # Check current URL — might be on a different success page
                current = page.url
                logger.info("Playwright: current URL after login: %s", current)
                if "/feed" not in current and "/mynetwork" not in current:
                    # Check for verification/captcha in page content
                    body = page.content()[:3000].lower()
                    if "captcha" in body:
                        raise AuthenticationError(
                            "Playwright login requires CAPTCHA"
                        )
                    if "pin" in body or "verification code" in body or "/checkpoint/challenge" in current:
                        # PIN verification required — try auto-handling via IMAP
                        if email_app_password:
                            logger.info("PIN verification detected — reading PIN from email via IMAP")
                            from phewdo_pro.utils.pin_reader import read_linkedin_pin
                            pin = read_linkedin_pin(email, email_app_password, max_wait_seconds=90)
                            if pin:
                                logger.info("Got PIN from email: %s — submitting", pin)
                                # Find the PIN input field and submit
                                try:
                                    pin_input = page.locator('input#input__email_verification_pin')
                                    if not pin_input.is_visible(timeout=5000):
                                        # Try alternative selectors
                                        pin_input = page.locator('input[name="pin"]')
                                    if not pin_input.is_visible(timeout=3000):
                                        pin_input = page.locator('input[type="text"]').first
                                    pin_input.click()
                                    pin_input.fill("")
                                    for digit in pin:
                                        pin_input.type(digit, delay=random.randint(50, 120))
                                    time.sleep(random.uniform(0.5, 1.0))
                                    # Click submit
                                    submit_btn = page.locator('button[type="submit"], button#email-pin-submit-button, form button').first
                                    submit_btn.click()
                                    # Wait for redirect to feed
                                    try:
                                        page.wait_for_url("**/feed**", timeout=30000)
                                        logger.info("Playwright: PIN accepted — redirected to feed")
                                    except Exception:
                                        final_url = page.url
                                        if "/feed" in final_url or "/mynetwork" in final_url:
                                            logger.info("Playwright: PIN accepted — on %s", final_url)
                                        else:
                                            raise AuthenticationError(
                                                f"PIN submitted but stuck at {final_url}"
                                            )
                                except AuthenticationError:
                                    raise
                                except Exception as pin_err:
                                    raise AuthenticationError(
                                        f"Failed to submit PIN: {pin_err}"
                                    )
                            else:
                                raise AuthenticationError(
                                    "PIN verification required but could not read PIN from email"
                                )
                        else:
                            raise AuthenticationError(
                                "Playwright login requires PIN verification (no email_app_password configured)"
                            )
                    # Maybe it's a different success URL
                    elif "linkedin.com" in current and "/login" not in current and "/uas/" not in current and "/checkpoint/" not in current:
                        logger.info("Playwright: on %s — treating as success", current)
                    else:
                        raise AuthenticationError(
                            f"Playwright login failed — stuck at {current}"
                        )

            # Step 4: Extract cookies
            cookies = context.cookies("https://www.linkedin.com")
            cookie_dict = {c["name"]: c["value"] for c in cookies}

            li_at = cookie_dict.get("li_at", "")
            jsessionid = cookie_dict.get("JSESSIONID", "").strip('"')

            if not li_at:
                raise AuthenticationError(
                    "Playwright login succeeded but no li_at cookie found"
                )

            logger.info(
                "Playwright login successful for %s — li_at=%s...",
                email, li_at[:20],
            )

            return cls(
                li_at=li_at,
                jsessionid=jsessionid,
                country_code=country_code,
                use_proxy=use_proxy,
            )

        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(
                f"Playwright login error: {type(e).__name__}: {e}"
            )
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass

    def verify_session(self) -> bool:
        """Verify the current session is still valid.

        Uses a standalone request with Cookie header directly to avoid
        any session cookie jar delivery issues.
        """
        try:
            headers = {
                "Cookie": f'li_at={self.li_at}; JSESSIONID="{self.jsessionid}"',
                "csrf-token": self.jsessionid,
                "accept": "application/vnd.linkedin.normalized+json+2.1",
                "x-restli-protocol-version": "2.0.0",
                "x-li-lang": "en_US",
                "user-agent": self.HEADERS["user-agent"],
            }
            logger.info(
                "verify_session: li_at=%s... jsessionid=%s proxy=%s",
                self.li_at[:20], self.jsessionid[:20],
                bool(self.session.proxies),
            )
            resp = requests.get(
                f"{self.API_BASE}/me",
                headers=headers,
                proxies=self.session.proxies or None,
                timeout=self.timeout,
                allow_redirects=False,
            )
            if resp.status_code in (301, 302, 303, 307, 308):
                logger.warning("Session redirect detected (HTTP %d) — cookies expired", resp.status_code)
                return False
            if resp.status_code == 401:
                return False
            if resp.status_code == 200:
                logger.info("Session verified OK")
                return True
            logger.warning("Session verify got HTTP %d", resp.status_code)
            return False
        except Exception as e:
            logger.warning("Session verification failed: %s", e)
            return False

    # ── Profile Methods ───────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(IOError),
        reraise=True,
    )
    def get_profile(
        self,
        public_id: Optional[str] = None,
    ) -> tuple[dict | None, dict | None]:
        """Fetch full profile via Voyager API.

        Returns:
            (parsed_profile_dict, raw_json) or (None, None) if inaccessible.
        """
        if not public_id:
            raise ValueError("public_id is required")

        params = {
            "decorationId": self.FULL_PROFILE_DECORATION,
            "memberIdentity": public_id,
            "q": "memberIdentity",
        }

        resp = self._get(
            f"{self.API_BASE}/identity/dash/profiles",
            params=params,
        )

        if resp.status_code in (403, 404):
            logger.info(
                "Profile inaccessible: %s (HTTP %d)", public_id, resp.status_code
            )
            return None, None

        if not resp.ok:
            raise IOError(
                f"LinkedIn API error {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        parsed = parse_linkedin_voyager_response(data, public_identifier=public_id)
        return parsed, data

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(IOError),
        reraise=True,
    )
    def get_connection_degree(self, public_id: str) -> int | None:
        """Fetch connection degree via lightweight TopCard decoration.

        Returns 1 (connected), 2, 3, or None.
        """
        resp = self._get(
            f"{self.API_BASE}/identity/dash/profiles",
            params={
                "decorationId": self.TOPCARD_DECORATION,
                "memberIdentity": public_id,
                "q": "memberIdentity",
            },
        )

        if resp.status_code in (403, 404):
            return None

        if not resp.ok:
            raise IOError(f"LinkedIn API error {resp.status_code}")

        return parse_connection_degree(resp.json())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(IOError),
        reraise=True,
    )
    def get_profile_contact_info(self, public_id: str) -> dict:
        """Fetch contact info (email, phone, websites) for a profile.

        Returns dict with keys: emailAddress, phoneNumbers, websites,
        twitterHandles, ims, birthDateOn.
        """
        resp = self._get(
            f"{self.API_BASE}/identity/profiles/{public_id}/profileContactInfo",
        )

        if resp.status_code in (403, 404):
            logger.info(
                "Contact info inaccessible: %s (HTTP %d)",
                public_id,
                resp.status_code,
            )
            return {}

        if not resp.ok:
            raise IOError(
                f"Contact info API error {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        return {
            "email": data.get("emailAddress"),
            "phone_numbers": [
                p.get("number") for p in (data.get("phoneNumbers") or [])
            ],
            "websites": [
                w.get("url") for w in (data.get("websites") or [])
            ],
            "twitter": [
                t.get("name") for t in (data.get("twitterHandles") or [])
            ],
        }

    # ── Search ────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(IOError),
        reraise=True,
    )
    def search_people(
        self,
        keywords: str,
        filters: dict | None = None,
        start: int = 0,
        count: int = 49,
    ) -> list[dict]:
        """Search LinkedIn People via Voyager dash search.

        Uses the current /search/dash/clusters endpoint (blended was deprecated).

        Args:
            keywords: Search query.
            filters: Additional search filters.
            start: Pagination offset.
            count: Results per page (max 49).

        Returns:
            List of dicts with: public_id, name, headline, location, urn_id, tracking_id.
        """
        # Build URL manually — LinkedIn's query syntax uses parentheses/commas
        # that must NOT be URL-encoded by requests
        from urllib.parse import quote
        encoded_kw = quote(keywords, safe="")
        query_str = (
            f"(keywords:{encoded_kw},"
            f"flagshipSearchIntent:SEARCH_SRP,"
            f"queryParameters:(resultType:List(PEOPLE)),"
            f"includeFiltersInResponse:true)"
        )
        url = (
            f"{self.API_BASE}/search/dash/clusters"
            f"?decorationId=com.linkedin.voyager.dash.deco.search.SearchClusterCollection-186"
            f"&origin=GLOBAL_SEARCH_HEADER"
            f"&q=all"
            f"&query={query_str}"
            f"&start={start}"
            f"&count={count}"
        )

        resp = self._get(url)

        if not resp.ok:
            raise IOError(
                f"Search API error {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        return self._parse_search_results(data)

    @staticmethod
    def _parse_search_results(data: dict) -> list[dict]:
        """Parse dash search cluster response into clean profile dicts."""
        results = []

        # Navigate the included/elements structure
        included = data.get("included", [])
        elements = data.get("elements", [])

        # Build a lookup of included entities by URN
        entity_map = {}
        for item in included:
            urn = item.get("entityUrn", "") or item.get("$recipeType", "")
            if urn:
                entity_map[urn] = item

        # Extract profiles from included entities
        for item in included:
            recipe = item.get("$recipeType", "")
            entity_urn = item.get("entityUrn", "")

            # Look for profile mini results
            if "MiniProfile" in recipe or "com.linkedin.voyager.dash.identity.profile.Profile" in recipe:
                public_id = item.get("publicIdentifier", "")
                if not public_id:
                    continue

                first = item.get("firstName", "")
                last = item.get("lastName", "")
                name = f"{first} {last}".strip()
                headline = item.get("occupation", "") or item.get("headline", "")

                urn_id = ""
                if entity_urn and "fsd_profile:" in entity_urn:
                    urn_id = entity_urn.split("fsd_profile:")[-1]
                elif entity_urn and "miniProfile:" in entity_urn:
                    urn_id = entity_urn.split("miniProfile:")[-1]

                tracking_id = item.get("trackingId", "")

                results.append({
                    "public_id": public_id,
                    "name": name,
                    "headline": headline,
                    "location": "",
                    "urn_id": urn_id,
                    "tracking_id": tracking_id,
                })
                continue

            # Also check search hit results for navigation URLs
            nav_url = item.get("navigationUrl", "")
            if "/in/" in nav_url:
                public_id = nav_url.split("/in/")[1].rstrip("/").split("?")[0]
                title = item.get("title", {})
                name = title.get("text", "") if isinstance(title, dict) else str(title)
                headline_obj = item.get("headline", {})
                headline = headline_obj.get("text", "") if isinstance(headline_obj, dict) else str(headline_obj or "")
                subline = item.get("subline", {})
                location = subline.get("text", "") if isinstance(subline, dict) else str(subline or "")

                urn_id = ""
                target_urn = item.get("objectUrn", "") or item.get("targetUrn", "")
                if target_urn and "fsd_profile:" in target_urn:
                    urn_id = target_urn.split("fsd_profile:")[-1]

                if public_id and not any(r["public_id"] == public_id for r in results):
                    results.append({
                        "public_id": public_id,
                        "name": name,
                        "headline": headline,
                        "location": location,
                        "urn_id": urn_id,
                        "tracking_id": item.get("trackingId", ""),
                    })

        # Fallback: try old-style elements structure
        if not results:
            for element in elements:
                items = element.get("elements", element.get("items", []))
                if not isinstance(items, list):
                    continue
                for item in items:
                    nav_url = item.get("navigationUrl", "")
                    if "/in/" in nav_url:
                        public_id = nav_url.split("/in/")[1].rstrip("/").split("?")[0]
                        title = item.get("title", {})
                        name = title.get("text", "") if isinstance(title, dict) else ""
                        if public_id:
                            results.append({
                                "public_id": public_id,
                                "name": name,
                                "headline": "",
                                "location": "",
                                "urn_id": "",
                                "tracking_id": "",
                            })

        return results

    # ── Connection Requests ───────────────────────────────────────

    def add_connection(
        self,
        urn_id: str,
        message: str = "",
    ) -> bool:
        """Send a connection request to a profile.

        Args:
            urn_id: The profile's URN ID (numeric part after fsd_profile:).
            message: Optional connection note (max 300 chars).

        Returns:
            True if connection request was sent (HTTP 201).
        """
        if message and len(message) > 300:
            message = message[:300]

        payload = {
            "trackingId": _generate_tracking_id(),
            "message": message,
            "invitations": [],
            "excludeInvitations": [],
            "invitee": {
                "com.linkedin.voyager.growth.invitation.InviteeProfile": {
                    "profileId": urn_id,
                }
            },
        }

        resp = self._post(
            f"{self.API_BASE}/growth/normInvitations",
            data=payload,
        )

        if resp.status_code == 201:
            logger.info("Connection request sent to URN %s", urn_id)
            return True

        logger.warning(
            "Connection request failed for URN %s: HTTP %d — %s",
            urn_id,
            resp.status_code,
            resp.text[:200],
        )
        return False

    # ── Messaging ─────────────────────────────────────────────────

    def send_message(
        self,
        message_body: str,
        conversation_urn_id: Optional[str] = None,
        recipients: Optional[list[str]] = None,
    ) -> bool:
        """Send a message via LinkedIn messaging.

        Args:
            message_body: The message text.
            conversation_urn_id: Existing conversation URN (for replies).
            recipients: List of profile URN IDs (for new conversations).

        Returns:
            True if message was sent successfully.
        """
        message_create = {
            "com.linkedin.voyager.messaging.create.MessageCreate": {
                "body": message_body,
                "attachments": [],
                "attributedBody": {
                    "text": message_body,
                    "attributes": [],
                },
                "mediaAttachments": [],
            }
        }

        if conversation_urn_id:
            # Reply to existing conversation
            payload = {
                "eventCreate": {"value": message_create},
            }
            url = (
                f"{self.API_BASE}/messaging/conversations/"
                f"{conversation_urn_id}/events?action=create"
            )
        elif recipients:
            # Start new conversation
            payload = {
                "eventCreate": {"value": message_create},
                "recipients": recipients,
                "subtype": "MEMBER_TO_MEMBER",
            }
            url = f"{self.API_BASE}/messaging/conversations?action=create"
        else:
            raise ValueError(
                "Either conversation_urn_id or recipients must be provided"
            )

        resp = self._post(url, data=payload)

        if resp.status_code in (200, 201):
            logger.info("Message sent successfully")
            return True

        logger.warning(
            "Message send failed: HTTP %d — %s",
            resp.status_code,
            resp.text[:200],
        )
        return False

    # ── Conversations ─────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(IOError),
        reraise=True,
    )
    def get_conversations(
        self, count: int = 20, start: int = 0
    ) -> list[dict]:
        """List recent messaging conversations.

        Returns list of conversation dicts.
        """
        resp = self._get(
            f"{self.API_BASE}/messaging/conversations",
            params={"keyVersion": "LEGACY_INBOX", "count": count, "start": start},
        )

        if not resp.ok:
            raise IOError(
                f"Conversations API error {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        return data.get("elements", [])
