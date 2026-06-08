"""
Playwright-based API discovery for the ONPE segunda vuelta results page.

This module is designed for a SINGLE one-time run. It opens the ONPE results
page in a visible browser, intercepts all network traffic, and captures the
XHR/fetch endpoint that returns vote/actas data. The discovered URL and request
headers are returned as a DiscoveryResult and written to .env by the CLI script.

Usage:
    result = await discover_api()
    # result.api_url  -> str, the captured endpoint URL
    # result.headers  -> dict, request headers needed to reach the endpoint

Do NOT use this module in the polling loop — it is browser-heavy and is meant
to run once to bootstrap config. All subsequent polling uses `scraper/fetcher.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ONPE_RESULTS_URL = "https://resultadosegundavuelta.onpe.gob.pe/main/resumen"
DISCOVERY_TIMEOUT_SECONDS: float = 30.0

# Keywords that indicate a response carries vote/actas data.
# Require at least MIN_KEYWORD_MATCHES to avoid matching navigation/menu JSON.
VOTE_DATA_KEYWORDS: tuple[str, ...] = (
    "actas",
    "votos",
    "candidato",
    "porcentaje",
    "sufragantes",
    "blancos",
    "nulos",
)
MIN_KEYWORD_MATCHES = 3


class DiscoveryError(RuntimeError):
    """Raised when API discovery fails for any reason."""


@dataclass
class DiscoveryResult:
    """Holds the endpoint URL and request headers captured during discovery."""

    api_url: str
    headers: dict[str, str]


def _looks_like_vote_data(body: str) -> bool:
    """Return True if the response body contains enough vote-related keywords.

    Requires MIN_KEYWORD_MATCHES distinct keywords to avoid false positives
    from navigation/menu JSON that contains words like 'actas' as text labels.
    """
    lower = body.lower()
    matches = sum(1 for keyword in VOTE_DATA_KEYWORDS if keyword in lower)
    return matches >= MIN_KEYWORD_MATCHES


async def discover_api() -> DiscoveryResult:
    """Launch a Playwright browser, navigate to the ONPE results page, and
    intercept the first XHR/fetch response that contains vote or actas data.

    The browser is launched in non-headless (visible) mode so that the page
    renders fully and triggers all dynamic API calls.

    Returns:
        DiscoveryResult with the captured API URL and request headers.

    Raises:
        DiscoveryError: If the Playwright Chromium binary is not installed,
            if no vote-data endpoint is found within the timeout, or if any
            other unrecoverable error occurs during discovery.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise DiscoveryError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )

    result_future: asyncio.Future[DiscoveryResult] = asyncio.get_running_loop().create_future()

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=False)
        except Exception as exc:
            error_msg = str(exc)
            if "Executable doesn't exist" in error_msg or "chromium" in error_msg.lower():
                raise DiscoveryError(
                    "Chromium binary is not installed. Run: playwright install chromium"
                ) from exc
            raise DiscoveryError(f"Failed to launch browser: {exc}") from exc

        context = await browser.new_context()
        page = await context.new_page()

        async def handle_response(response) -> None:  # type: ignore[no-untyped-def]
            """Intercept each network response and check for vote data."""
            if result_future.done():
                return

            url: str = response.url
            # Only inspect responses from ONPE domains
            if "onpe.gob.pe" not in url:
                return

            # Skip static assets — translation files, bundles, fonts, etc.
            skip_paths = ("/assets/", "/i18n/", ".js", ".css", ".woff", ".png", ".svg")
            if any(p in url for p in skip_paths):
                return

            # Only inspect JSON responses — skip JS bundles, CSS, HTML, etc.
            content_type: str = response.headers.get("content-type", "")
            if "json" not in content_type:
                return

            try:
                body: str = await response.text()
            except Exception:
                return

            if not _looks_like_vote_data(body):
                return

            # Capture the request headers that were sent for this response.
            # Strip HTTP/2 pseudo-headers (:authority, :method, :path, :scheme)
            # — they are internal to HTTP/2 and invalid as httpx request headers.
            request = response.request
            try:
                raw_headers: dict[str, str] = await request.all_headers()
            except Exception:
                raw_headers = dict(request.headers)
            request_headers = {k: v for k, v in raw_headers.items() if not k.startswith(":")}

            logger.info("Discovered vote-data endpoint: %s", url)
            result_future.set_result(DiscoveryResult(api_url=url, headers=request_headers))

        page.on("response", handle_response)

        try:
            await page.goto(ONPE_RESULTS_URL, wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            logger.warning("Page navigation warning (non-fatal): %s", exc)

        # Wait for the async handler to capture a result, up to the timeout
        try:
            discovery = await asyncio.wait_for(result_future, timeout=DISCOVERY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await browser.close()
            raise DiscoveryError(
                f"No vote-data API endpoint found within {DISCOVERY_TIMEOUT_SECONDS:.0f} seconds. "
                "The ONPE page may have changed structure or uses a different data loading "
                "mechanism. Check the browser's Network tab manually for candidate URLs."
            )

        await browser.close()
        return discovery
