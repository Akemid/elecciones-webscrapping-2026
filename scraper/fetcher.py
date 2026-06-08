"""
HTTP client module for the ONPE segunda vuelta scraper.

Fetches the raw API response using httpx with browser-like headers and
tenacity-based retry logic. If all retry attempts are exhausted, a
FetchError is raised and the caller (main.py / scheduler.py) should
fall back to Playwright-based extraction (scraper/discover.py).

This module contains NO Playwright code — concerns are kept separate.
"""

from __future__ import annotations

import logging
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger(__name__)

# Retry policy: 3 attempts, exponential backoff 1s → 2s → 4s
_MAX_ATTEMPTS = 3
_WAIT_MIN_SECONDS = 1
_WAIT_MAX_SECONDS = 4

SLOW_THRESHOLD_SECONDS: float = 30.0


class FetchError(RuntimeError):
    """Raised when all retry attempts are exhausted without a successful response.

    Caller should consider falling back to Playwright-based extraction
    (see scraper/discover.py) when this exception is raised.
    """


def _should_retry(exc: BaseException) -> bool:
    """Return True for transient HTTP errors worth retrying."""
    if isinstance(exc, httpx.HTTPError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


async def fetch(config: Config, url: str | None = None) -> tuple[bytes, float]:
    """Fetch the ONPE results API and return the raw response body and duration.

    Uses browser-like headers from config.onpe_session_headers to avoid
    basic bot-detection measures. Retries up to 3 times with exponential
    backoff (1s, 2s, 4s) on transient network errors or 5xx responses.

    Args:
        config: Validated runtime configuration. Must have a non-empty
            onpe_api_url and optionally onpe_session_headers.

    Returns:
        A tuple of (raw_bytes, duration_seconds) where raw_bytes is the
        response body and duration_seconds is the wall-clock fetch time.

    Raises:
        FetchError: If all retry attempts are exhausted. The caller should
            fall back to Playwright-based extraction as a next step.
    """
    target_url = url or config.onpe_api_url
    start = time.monotonic()

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=wait_exponential(
            multiplier=1, min=_WAIT_MIN_SECONDS, max=_WAIT_MAX_SECONDS
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=False,
    )
    async def _attempt() -> bytes:
        attempt_start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                headers=config.onpe_session_headers,
                follow_redirects=True,
                timeout=15.0,
            ) as client:
                response = await client.get(target_url)
                response.raise_for_status()
                duration = time.monotonic() - attempt_start
                logger.info(
                    "Fetch attempt succeeded: status=%d, duration=%.3fs, url=%s",
                    response.status_code,
                    duration,
                    target_url,
                )
                return response.content
        except httpx.HTTPStatusError as exc:
            duration = time.monotonic() - attempt_start
            logger.warning(
                "Fetch attempt failed: status=%d, duration=%.3fs, url=%s",
                exc.response.status_code,
                duration,
                target_url,
            )
            raise
        except httpx.HTTPError as exc:
            duration = time.monotonic() - attempt_start
            logger.warning(
                "Fetch attempt failed: error=%s, duration=%.3fs, url=%s",
                exc,
                duration,
                target_url,
            )
            raise

    try:
        raw = await _attempt()
    except Exception as exc:
        total_duration = time.monotonic() - start
        raise FetchError(
            f"All {_MAX_ATTEMPTS} fetch attempts exhausted for {target_url!r} "
            f"after {total_duration:.3f}s. "
            "Consider falling back to Playwright-based extraction (scraper/discover.py)."
        ) from exc

    total_duration = time.monotonic() - start

    if total_duration > SLOW_THRESHOLD_SECONDS:
        logger.warning(
            "Fetch exceeded %.0fs threshold (%.3fs)",
            SLOW_THRESHOLD_SECONDS,
            total_duration,
        )
    else:
        logger.info("Fetch completed in %.3fs", total_duration)

    return raw, total_duration
