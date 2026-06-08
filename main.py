"""
ONPE Segunda Vuelta Scraper — entry point.

Three execution modes (select via CLI flag):

  --discover   Run the one-time Playwright discovery (scripts/discover_api.py),
               write ONPE_API_URL and ONPE_SESSION_HEADERS to .env, then exit.

  --once       Single fetch → parse → diff → store cycle. Default mode.

  --daemon     Start the APScheduler-based polling daemon (scraper/scheduler.py).
               Runs until SIGTERM / SIGINT.

Usage:
    python main.py --discover
    python main.py --once
    python main.py --daemon
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from config import ConfigurationError, load_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="ONPE Segunda Vuelta Scraper",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--discover",
        action="store_true",
        help="Run one-time Playwright API discovery and write results to .env, then exit.",
    )
    mode.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="(Default) Run a single fetch → parse → store cycle and exit.",
    )
    mode.add_argument(
        "--daemon",
        action="store_true",
        help="Start the APScheduler polling daemon (runs until SIGTERM/SIGINT).",
    )
    return parser


def _run_discover() -> None:
    """Delegate to the discovery CLI script."""
    import runpy
    runpy.run_module("scripts.discover_api", run_name="__main__")


def _run_daemon() -> None:
    """Start the APScheduler daemon (T-11)."""
    try:
        from scraper.scheduler import start_daemon  # type: ignore[import]
    except ImportError as exc:
        print(f"ERROR: scheduler not available ({exc}). Implement T-11 first.")
        sys.exit(1)
    start_daemon()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.discover:
        _run_discover()
        return

    if args.daemon:
        _run_daemon()
        return

    # Default: --once
    try:
        config = load_config()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}")
        sys.exit(1)

    from scraper.pipeline import run_once
    asyncio.run(run_once(config))


if __name__ == "__main__":
    main()
