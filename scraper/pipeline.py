"""
Single-cycle scrape pipeline for the ONPE segunda vuelta scraper.

Wires together: config → fetch (2 endpoints) → hash-check → parse → store → delta.
Called by main.py (--once mode) and by scheduler.py (daemon mode).

Two endpoints are fetched per cycle:
  - TOTALES_PATH: actas % and vote totals
  - CANDIDATOS_PATH: per-candidate vote counts and percentages

Fetch strategy:
  1. httpx with tenacity retries (primary).
  2. Playwright stealth browser (fallback on FetchError — e.g. 403/429).
  If both fail the process exits with code 1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from config import Config
from models.snapshot import RegionResult
from scraper.differ import compute_delta, compute_hash, get_prev_snapshot, has_changed
from scraper.fetcher import FetchError, fetch
from scraper.parser import ParseError, parse_snapshot
from scraper.storage import Storage

# Endpoint paths — stable for the SEP2026 election cycle
TOTALES_PATH = "/resumen-general/totales?idEleccion=10&tipoFiltro=eleccion"
CANDIDATOS_PATH = "/eleccion-presidencial/participantes-ubicacion-geografica-nombre?idEleccion=10&tipoFiltro=eleccion"
DEPTS_PATH = "/ubigeos/departamentos?idEleccion=10&idAmbitoGeografico=1"
REGION_CANDIDATOS_PATH = (
    "/eleccion-presidencial/participantes-ubicacion-geografica-nombre"
    "?tipoFiltro=ubigeo_nivel_01&idAmbitoGeografico=1&idEleccion=10&ubigeoNivel1={ubigeo}"
)


def _base_url(config: Config) -> str:
    parsed = urlparse(config.onpe_api_url)
    return f"{parsed.scheme}://{parsed.netloc}/presentacion-backend"


def _build_urls(config: Config) -> tuple[str, str]:
    """Derive national endpoint URLs from config.onpe_api_url base."""
    base = _base_url(config)
    return base + TOTALES_PATH, base + CANDIDATOS_PATH

logger = logging.getLogger(__name__)

SLOW_THRESHOLD_SECONDS: float = 30.0


async def _fetch_regions(
    config: Config, base: str, c1_code: str, c2_code: str
) -> list[RegionResult]:
    """Fetch candidatos for all 25 departments in parallel.

    c1_code / c2_code: codigoAgrupacionPolitica from the national candidatos response.
    Regional candidato_1 always matches national candidato_1, regardless of who
    leads in that region.

    Returns list of RegionResult. Skips departments that fail (logs warning).
    """
    # Step 1: get department ubigeos
    try:
        depts_raw, _ = await fetch(config, url=base + DEPTS_PATH)
        depts: list[dict] = json.loads(depts_raw).get("data", [])
    except Exception as exc:
        logger.warning("Could not fetch department list: %s — skipping regional data", exc)
        return []

    if not depts:
        return []

    # Step 2: fetch all departments in parallel
    async def _fetch_one(dept: dict) -> list[RegionResult]:
        ubigeo = dept["ubigeo"]
        nombre = dept["nombre"]
        url = base + REGION_CANDIDATOS_PATH.format(ubigeo=ubigeo)
        try:
            raw, _ = await fetch(config, url=url)
            items: list[dict] = json.loads(raw).get("data", [])
            by_code = {c["codigoAgrupacionPolitica"]: c for c in items if c.get("dniCandidato")}
            c1 = by_code.get(c1_code)
            c2 = by_code.get(c2_code)
            if not c1 or not c2:
                logger.warning("Could not match candidates for %s (codes %s/%s, got %s)", nombre, c1_code, c2_code, list(by_code.keys()))
                return []
            return [RegionResult(
                region_codigo=ubigeo,
                region_nombre=nombre,
                candidato_1_votos=int(c1["totalVotosValidos"]),
                candidato_1_pct=float(c1["porcentajeVotosValidos"]),
                candidato_2_votos=int(c2["totalVotosValidos"]),
                candidato_2_pct=float(c2["porcentajeVotosValidos"]),
            )]
        except Exception as exc:
            logger.warning("Regional fetch failed for %s (%s): %s", nombre, ubigeo, exc)
            return []

    results = await asyncio.gather(*[_fetch_one(d) for d in depts])
    return [r for batch in results for r in batch]


async def _fetch_with_playwright_fallback(config: Config) -> bytes:
    """Playwright stealth fallback for when httpx retries are exhausted.

    Navigates to the ONPE API URL using a real browser and captures the
    response body. Used only after FetchError from the primary httpx path.

    Args:
        config: Validated runtime configuration.

    Returns:
        Raw response bytes.

    Raises:
        FetchError: If the Playwright fetch also fails for any reason.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise FetchError(
            "Playwright is not installed — cannot use stealth fallback. "
            "Run: pip install playwright && playwright install chromium"
        )

    logger.info("Attempting Playwright stealth fallback for %s", config.onpe_api_url)

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                extra_http_headers=config.onpe_session_headers,
            )
            page = await context.new_page()

            body_bytes: bytes | None = None

            async def capture_response(response) -> None:  # type: ignore[no-untyped-def]
                nonlocal body_bytes
                if body_bytes is not None:
                    return
                if config.onpe_api_url in response.url:
                    try:
                        body_bytes = await response.body()
                    except Exception:
                        pass

            page.on("response", capture_response)
            await page.goto(config.onpe_api_url, wait_until="networkidle", timeout=60_000)

            await browser.close()

            if body_bytes is None:
                raise FetchError(
                    "Playwright fallback: no response body captured for the ONPE API URL."
                )
            logger.info("Playwright fallback succeeded: %d bytes", len(body_bytes))
            return body_bytes

    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"Playwright stealth fallback failed: {exc}") from exc


async def run_once(config: Config) -> None:
    """Execute one full fetch → parse → diff → store cycle.

    Logs duration and prints a one-line summary to stdout.
    Exits the process with code 1 on unrecoverable errors (fetch/parse
    failures) so that CI and the scheduler can detect failures cleanly.

    Args:
        config: Validated runtime configuration.
    """
    storage = Storage(config)
    storage.init_db()

    cycle_start = time.monotonic()
    scraped_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("Scrape cycle starting at %s", scraped_at)

    # --- Fetch national + regional data ---
    base = _base_url(config)
    totales_url, candidatos_url = _build_urls(config)
    try:
        (totales_raw, _), (candidatos_raw, _) = await asyncio.gather(
            fetch(config, url=totales_url),
            fetch(config, url=candidatos_url),
        )
    except FetchError as primary_exc:
        logger.warning("Primary fetch failed, trying Playwright fallback: %s", primary_exc)
        try:
            totales_raw = await _fetch_with_playwright_fallback(config)
            candidatos_raw = totales_raw  # fallback only gets one response
        except FetchError as fallback_exc:
            logger.error("Both fetch strategies failed. Primary: %s | Fallback: %s", primary_exc, fallback_exc)
            print(f"[{scraped_at}] ERROR: all fetch strategies exhausted — {fallback_exc}")
            sys.exit(1)

    # Extract national c1/c2 codes to ensure consistent ordering in regional data
    try:
        all_candidatos: list[dict] = json.loads(candidatos_raw).get("data", [])
        real_candidates = sorted(
            [c for c in all_candidatos if c.get("dniCandidato")],
            key=lambda c: c.get("totalVotosValidos", 0),
            reverse=True,
        )
        c1_code = real_candidates[0]["codigoAgrupacionPolitica"] if len(real_candidates) >= 2 else ""
        c2_code = real_candidates[1]["codigoAgrupacionPolitica"] if len(real_candidates) >= 2 else ""
    except Exception:
        c1_code = c2_code = ""

    # Fetch regional data (25 departments in parallel)
    regions = await _fetch_regions(config, base, c1_code, c2_code)
    logger.info("Regional data: %d departments fetched", len(regions))

    # --- Deduplication check (hash combined responses) ---
    combined_raw = totales_raw + candidatos_raw
    response_hash = compute_hash(combined_raw)
    if not has_changed(combined_raw, storage):
        elapsed = time.monotonic() - cycle_start
        print(
            f"[{scraped_at}] no change "
            f"(hash={response_hash[:12]}…, duration={elapsed:.2f}s)"
        )
        logger.info("Cycle done (no change): %.3fs", elapsed)
        return

    # --- Parse ---
    try:
        snapshot = parse_snapshot(totales_raw, candidatos_raw, scraped_at=scraped_at, response_hash=response_hash, regions=regions)
    except ParseError as exc:
        logger.error("Parse failed: %s", exc)
        print(f"[{scraped_at}] ERROR: parse failed — {exc}")
        sys.exit(1)

    # --- Read prev for delta (before saving, so we don't read ourselves) ---
    prev_snapshot_id = storage.get_last_snapshot_id()
    prev = get_prev_snapshot(storage) if prev_snapshot_id is not None else None
    change = None
    if prev is not None and prev_snapshot_id is not None:
        change = compute_delta(snapshot, prev_snapshot_id, storage)

    # --- Store ---
    snapshot_id = storage.save_snapshot(snapshot)
    storage.write_json(snapshot, combined_raw)

    if change is not None:
        change.snapshot_id = snapshot_id
        storage.save_change(change)

    elapsed = time.monotonic() - cycle_start
    if elapsed > SLOW_THRESHOLD_SECONDS:
        logger.warning("Scrape exceeded %.0fs threshold (%.3fs)", SLOW_THRESHOLD_SECONDS, elapsed)

    print(
        f"[{scraped_at}] snapshot saved "
        f"| actas={snapshot.actas_procesadas_pct:.2f}% "
        f"| {snapshot.candidato_1_nombre}={snapshot.candidato_1_pct:.2f}% "
        f"vs {snapshot.candidato_2_nombre}={snapshot.candidato_2_pct:.2f}% "
        f"| duration={elapsed:.2f}s"
    )
    logger.info("Cycle done (new snapshot): id=%d, %.3fs", snapshot_id, elapsed)
