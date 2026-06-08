# Proposal: ONPE Segunda Vuelta Scraper

## Intent

Peru's ONPE publishes live presidential runoff results at `resultadosegundavuelta.onpe.gob.pe/main/resumen` but provides no API, no export, and no historical tracking. The election was held June 7 2026; counting is ~92% complete and the platform will be decommissioned within days. We need a recurring scraper that captures national + regional results every 5-15 minutes, building a time-series dataset suitable for later dashboard visualization.

## Scope

### In Scope
- API endpoint discovery tool (Playwright network interception)
- Recurring HTTP scraper (httpx with stealth headers)
- Playwright stealth fallback when direct API fails
- National summary + per-region breakdown capture
- Time-series storage: JSON snapshots + SQLite queryable database
- Hash-based change detection with structured deltas
- APScheduler-based local daemon with configurable interval
- GitHub Actions cron as cloud fallback

### Out of Scope
- Dashboard / visualization UI (future phase)
- AWS Lambda / EventBridge deployment (documented but deferred)
- Per-distrito or per-mesa granularity (regional level is sufficient)
- Real-time WebSocket streaming
- Historical backfill of already-missed snapshots

## Capabilities

### New Capabilities
- `api-discovery`: Playwright-based network interception to find ONPE backend API URLs and response shapes
- `result-scraper`: Recurring HTTP fetcher with retry, stealth headers, and Playwright fallback
- `snapshot-storage`: Dual-write storage (JSON files + SQLite) with hash-based deduplication and delta tracking
- `scheduler`: APScheduler daemon with configurable interval and graceful shutdown

### Modified Capabilities
- None (greenfield project)

## Approach

**Hybrid: Playwright discovery + httpx polling** (Option C from exploration).

1. **Phase 1 - Discovery**: Run Playwright non-headless once, intercept XHR/fetch to ONPE backend, log API URLs and response schema. Output: hardcoded API URL + required headers.
2. **Phase 2 - Scraper + Storage**: `httpx` client with browser-like headers polls the discovered API. Each response is hashed; new data gets stored as JSON snapshot + SQLite row with computed deltas.
3. **Phase 3 - Scheduling**: APScheduler daemon wraps the scraper in a configurable interval loop (default 15 min). GitHub Actions workflow provided as alternative.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `scraper/discovery.py` | New | Playwright network interceptor for API URL extraction |
| `scraper/fetcher.py` | New | httpx client + Playwright stealth fallback |
| `scraper/storage.py` | New | SQLite + JSON dual-write with deduplication |
| `scraper/differ.py` | New | SHA-256 hash comparison + structured delta computation |
| `scraper/models.py` | New | Typed dataclasses for snapshot and delta data |
| `scraper/main.py` | New | APScheduler daemon entry point |
| `config.py` | New | Interval, API URL, output paths, headers |
| `pyproject.toml` | New | Dependencies: httpx, playwright, apscheduler, deepdiff |
| `.github/workflows/scraper.yml` | New | Optional GitHub Actions 15-min cron |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| API URL unknown until discovery phase runs | High | Phase 1 is a blocking prerequisite; Playwright DOM scrape as ultimate fallback |
| ONPE headless detection blocks httpx | High | Browser-like headers + cookie from Playwright session; stealth fallback |
| Platform decommissioned before scraper runs | Medium | Time-critical: build Phase 1+2 first, scheduler later |
| Rate limiting at <5 min intervals | Low | Default to 15 min; configurable; exponential backoff on 429 |
| API uses WebSocket/SSE instead of REST | Low | Playwright intercept will reveal transport; adjust fetcher accordingly |

## Rollback Plan

Each phase is independently revertible. Discovery tool is read-only (no side effects). Scraper writes only to local `data/` directory. SQLite and JSON files can be deleted to reset. APScheduler daemon stops cleanly on SIGTERM. No external state is mutated.

## Dependencies

- Python 3.11+
- Playwright (with Chromium browser binary)
- httpx, apscheduler, deepdiff
- A machine with a display (or Xvfb) for the initial Playwright discovery step

## Success Criteria

- [ ] Discovery tool identifies at least one ONPE API endpoint URL
- [ ] Scraper captures national summary + all 26 regional breakdowns per snapshot
- [ ] SQLite contains time-series data queryable by timestamp and region
- [ ] Change detection skips duplicate snapshots (hash match)
- [ ] Daemon runs unattended for 2+ hours at 15-min intervals without error
- [ ] JSON snapshots are valid, timestamped, and git-diffable
