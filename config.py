"""
Configuration module for the ONPE segunda vuelta scraper.

Loads runtime settings from environment variables or a .env file.
All secrets and API endpoints must be set via environment — no hardcoding.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

VALID_INTERVALS: frozenset[int] = frozenset({5, 10, 15})
DEFAULT_INTERVAL_MINUTES: int = 10
DEFAULT_DATA_DIR: str = "./data"


class ConfigurationError(ValueError):
    """Raised when a required configuration variable is missing or invalid."""


@dataclass
class Config:
    """Validated runtime configuration.

    Attributes:
        onpe_api_url: Base URL for the ONPE results API endpoint.
        scraper_interval_minutes: Polling interval in minutes (5, 10, or 15).
        data_dir: Directory for JSON snapshots and the SQLite database.
        onpe_session_headers: HTTP headers required to reach the ONPE API.
        db_path: Path to the SQLite database file. Defaults to
            ``{data_dir}/election.db`` when not set via DB_PATH env var.
    """

    onpe_api_url: str
    scraper_interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    data_dir: str = DEFAULT_DATA_DIR
    onpe_session_headers: dict[str, str] = field(default_factory=dict)
    db_path: str = ""  # resolved to {data_dir}/election.db when empty


def load_config(discovery_mode: bool = False) -> Config:
    """Load and validate configuration from environment / .env file.

    Args:
        discovery_mode: When True, ONPE_API_URL is not required.
            Use this during the one-time Playwright discovery step before
            the URL is known.

    Returns:
        A fully validated Config instance.

    Raises:
        ConfigurationError: If a required variable is missing or has an
            invalid value (e.g. unsupported interval).
    """
    load_dotenv()

    # --- ONPE_API_URL ---
    api_url = os.getenv("ONPE_API_URL", "").strip()
    if not api_url and not discovery_mode:
        raise ConfigurationError(
            "ONPE_API_URL is required but not set. "
            "Run `python scripts/discover_api.py` first to discover the endpoint."
        )

    # --- SCRAPER_INTERVAL_MINUTES ---
    # Note: the original spec doc used SCRAPE_INTERVAL_MINUTES (no trailing R).
    # The implementation chose SCRAPER_INTERVAL_MINUTES for clarity and it is
    # used consistently across all files. This is a documented spec deviation.
    raw_interval = os.getenv("SCRAPER_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES)).strip()
    try:
        interval = int(raw_interval)
    except ValueError:
        raise ConfigurationError(
            f"SCRAPER_INTERVAL_MINUTES must be an integer, got: {raw_interval!r}"
        )
    if interval not in VALID_INTERVALS:
        raise ConfigurationError(
            f"SCRAPER_INTERVAL_MINUTES must be one of {sorted(VALID_INTERVALS)}, got: {interval}"
        )

    # --- DATA_DIR ---
    data_dir = os.getenv("DATA_DIR", DEFAULT_DATA_DIR).strip() or DEFAULT_DATA_DIR

    # --- DB_PATH ---
    # Optional override for the SQLite file path.
    # Defaults to {data_dir}/election.db when not set.
    db_path = os.getenv("DB_PATH", "").strip()
    if not db_path:
        db_path = f"{data_dir}/election.db"

    # --- ONPE_SESSION_HEADERS ---
    raw_headers = os.getenv("ONPE_SESSION_HEADERS", "{}").strip() or "{}"
    try:
        session_headers: dict[str, str] = json.loads(raw_headers)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"ONPE_SESSION_HEADERS must be valid JSON, got: {raw_headers!r}. Error: {exc}"
        )
    if not isinstance(session_headers, dict):
        raise ConfigurationError(
            f"ONPE_SESSION_HEADERS must be a JSON object, got: {type(session_headers).__name__}"
        )

    return Config(
        onpe_api_url=api_url,
        scraper_interval_minutes=interval,
        data_dir=data_dir,
        onpe_session_headers=session_headers,
        db_path=db_path,
    )
