"""
APScheduler-based polling daemon for the ONPE segunda vuelta scraper.

Runs run_once() on a configurable interval until SIGTERM or SIGINT.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config, load_config
from scraper.pipeline import run_once

logger = logging.getLogger(__name__)


class Scraper:
    """Manages the APScheduler daemon lifecycle."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler()

    def _add_job(self) -> None:
        interval_minutes = self._config.scraper_interval_minutes
        self._scheduler.add_job(
            run_once,
            trigger="interval",
            minutes=interval_minutes,
            args=[self._config],
            id="scrape_job",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(tz=timezone.utc),  # fire immediately on start
        )
        logger.info("Scheduler started. Interval: %dmin", interval_minutes)

    async def _run_async(self) -> None:
        """Start scheduler inside a running event loop and wait for stop signal."""
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _shutdown() -> None:
            logger.info("Shutting down...")
            self._scheduler.remove_all_jobs()
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, _shutdown)
        loop.add_signal_handler(signal.SIGINT, _shutdown)

        self._add_job()
        self._scheduler.start()
        print("Daemon running. Press Ctrl+C to stop.")

        await stop_event.wait()

    def run(self) -> None:
        """Block until stop signal."""
        asyncio.run(self._run_async())


def start_daemon() -> None:
    """Load config and run the scheduler daemon.

    This is the entry point called by main.py --daemon.
    """
    config = load_config()
    scraper = Scraper(config)
    scraper.run()
