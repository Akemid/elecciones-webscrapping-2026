"""
CLI script for one-time ONPE API endpoint discovery.

Launches a Playwright browser, navigates to the ONPE results page, intercepts
the vote-data API endpoint, and writes the discovered URL and session headers
to a .env file so that the polling scraper can use them.

Usage:
    python scripts/discover_api.py
    python scripts/discover_api.py --output .env
    python scripts/discover_api.py --output /path/to/custom.env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Allow running as `python scripts/discover_api.py` from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.discover import DiscoveryError, discover_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _update_env_file(env_path: Path, api_url: str, headers: dict[str, str]) -> None:
    """Write or update ONPE_API_URL and ONPE_SESSION_HEADERS in the env file.

    Existing lines for these two keys are replaced; all other lines are kept.
    If the file does not exist it is created.

    Args:
        env_path: Path to the target .env file.
        api_url: The discovered ONPE API endpoint URL.
        headers: The request headers captured during discovery.
    """
    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    # Remove any existing ONPE_API_URL / ONPE_SESSION_HEADERS lines
    filtered = [
        line
        for line in existing_lines
        if not line.startswith("ONPE_API_URL=") and not line.startswith("ONPE_SESSION_HEADERS=")
    ]

    headers_json = json.dumps(headers, ensure_ascii=False)
    filtered.append(f"ONPE_API_URL={api_url}")
    filtered.append(f"ONPE_SESSION_HEADERS={headers_json}")

    env_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the ONPE segunda vuelta API endpoint using Playwright "
            "and write the result to a .env file."
        ),
    )
    parser.add_argument(
        "--output",
        default=".env",
        metavar="FILE",
        help="Path to the .env file to write (default: .env)",
    )
    return parser


async def _run(output_path: Path) -> int:
    """Execute discovery and persist results.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    logger.info("Starting ONPE API discovery — a browser window will open.")
    logger.info("Please wait up to 30 seconds for vote data to load...")

    try:
        result = await discover_api()
    except DiscoveryError as exc:
        logger.error("Discovery failed: %s", exc)
        return 1

    print()
    print("=" * 60)
    print("Discovery successful!")
    print(f"  API URL : {result.api_url}")
    print(f"  Headers : {len(result.headers)} captured")
    print("=" * 60)
    print()

    _update_env_file(output_path, result.api_url, result.headers)

    print(f"Written to: {output_path.resolve()}")
    print()
    print("Next step:")
    print("  python main.py --once     # run a single scrape cycle")
    print("  python main.py --daemon   # start the polling daemon")
    print()

    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    output_path = Path(args.output)
    exit_code = asyncio.run(_run(output_path))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
