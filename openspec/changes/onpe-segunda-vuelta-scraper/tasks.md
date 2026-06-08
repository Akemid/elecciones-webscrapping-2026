# Tasks: ONPE Segunda Vuelta Scraper

## Phase 1 — Discovery & Bootstrap

### T-01 · Project scaffolding
**Spec refs**: scheduler/Configuration via Environment, out-of-scope constraints
**Description**: Create `pyproject.toml` (dependencies: playwright, httpx, tenacity, apscheduler, deepdiff, python-dotenv), `.gitignore` (data/, .env, __pycache__/, *.db), and `.env.example` (ONPE_API_URL, SCRAPE_INTERVAL_MINUTES, DATA_DIR, DB_PATH). Create empty package markers: `scraper/__init__.py`, `models/__init__.py`, `scripts/__init__.py`.
**Files**: `pyproject.toml`, `.gitignore`, `.env.example`, `scraper/__init__.py`, `models/__init__.py`, `scripts/__init__.py`
**Dependencies**: none
**Complexity**: S
**Parallel**: YES — can run with T-02, T-03

---

### T-02 · Data models
**Spec refs**: result-scraper/National Summary Fetch, result-scraper/Regional Breakdown Fetch, snapshot-storage/Delta Computation
**Description**: Implement `Snapshot`, `RegionResult`, and `ChangeRecord` dataclasses as defined in the design contracts. Include field-level docstrings noting which fields are speculative until T-04 runs.
**Files**: `models/snapshot.py`
**Dependencies**: none
**Complexity**: S
**Parallel**: YES — can run with T-01, T-03

---

### T-03 · Configuration module
**Spec refs**: scheduler/Configuration via Environment (all scenarios)
**Description**: Implement `config.py` using `python-dotenv`. Load and validate `ONPE_API_URL`, `SCRAPE_INTERVAL_MINUTES` (validate against {5,10,15}), `DATA_DIR`, `DB_PATH`. Raise typed `ConfigurationError` for missing required vars. Export a `Config` dataclass.
**Files**: `config.py`
**Dependencies**: T-01 (pyproject for dotenv dep)
**Complexity**: S
**Parallel**: YES — can run with T-02 once T-01 done

---

### T-04 · Playwright API discovery
**Spec refs**: api-discovery/Network Interception Discovery (all three scenarios)
**Description**: Implement `scraper/discover.py` with an async Playwright function that opens the ONPE results page, intercepts XHR/fetch requests, filters responses containing vote/actas data, and returns candidate URLs + headers. Handles browser-binary-missing error (exit with `playwright install chromium` hint) and no-endpoint-found exit with non-zero code.
**Files**: `scraper/discover.py`
**Dependencies**: T-01, T-02, T-03
**Complexity**: M
**Parallel**: NO — gates T-07 (parser field mapping)

---

### T-05 · Discovery CLI script
**Spec refs**: api-discovery/Network Interception Discovery — "output to stdout and to a config file"
**Description**: Implement `scripts/discover_api.py` as a CLI entry point that calls `discover.py`, prints discovered URL + headers, and appends/updates `ONPE_API_URL` in the `.env` file. Accepts `--output .env` flag.
**Files**: `scripts/discover_api.py`
**Dependencies**: T-04
**Complexity**: S
**Parallel**: NO — sequential after T-04

---

## Phase 2 — Scraper + Storage

### T-06 · HTTP fetcher
**Spec refs**: result-scraper/National Summary Fetch (network failure + 403/429 scenarios), result-scraper/Scrape Duration Logging
**Description**: Implement `scraper/fetcher.py` with an httpx async client. Uses browser-like headers from config, tenacity retry (3 attempts, exponential backoff), 30s scrape-duration tracking with WARNING threshold, and Playwright-stealth fallback when httpx gets 403/429. Returns `tuple[str, bytes]` (url, raw_body).
**Files**: `scraper/fetcher.py`
**Dependencies**: T-01, T-02, T-03
**Complexity**: M
**Parallel**: YES — can run with T-07, T-08 after T-03

---

### T-07 · Response parser
**Spec refs**: result-scraper/National Summary Fetch (Snapshot fields), result-scraper/Regional Breakdown Fetch (RegionEntry fields + 26-region coverage check)
**Description**: Implement `scraper/parser.py` with `parse_national(raw: bytes) -> Snapshot` and `parse_regional(raw: bytes) -> list[RegionResult]`. Includes 26-region coverage check with WARNING log for partial data. NOTE: field mapping is speculative until T-04 runs; use placeholder keys and document with TODO comments.
**Files**: `scraper/parser.py`
**Dependencies**: T-02, T-04 (for real field names — mark placeholders until discovery runs)
**Complexity**: M
**Parallel**: Can start with stubs after T-02; finalize after T-04

---

### T-08 · Storage layer
**Spec refs**: snapshot-storage/Dual-Write Storage, snapshot-storage/SQLite Query Performance
**Description**: Implement `scraper/storage.py` with `init_db(config)` (creates snapshots, regions, changes tables with FK constraints and indexes on `scraped_at`, `changes(snapshot_id)`), `save_snapshot(snapshot, raw_json, config) -> int`, and `get_last_hash(config) -> str | None`. JSON filename format: `snapshot_{ISO8601_safe}.json` in `DATA_DIR`.
**Files**: `scraper/storage.py`
**Dependencies**: T-01, T-02, T-03
**Complexity**: M
**Parallel**: YES — can run with T-06, T-07

---

### T-09 · Differ / deduplication
**Spec refs**: snapshot-storage/Hash-Based Deduplication, snapshot-storage/Delta Computation and Storage
**Description**: Implement `scraper/differ.py` with `has_changed(raw_body, last_hash) -> tuple[bool, str]` (SHA-256 comparison) and `compute_delta(new_snapshot, prev_snapshot) -> ChangeRecord` using deepdiff. Log `Snapshot deduplicated — no new data` on match.
**Files**: `scraper/differ.py`
**Dependencies**: T-02, T-08 (needs ChangeRecord + storage types)
**Complexity**: S
**Parallel**: YES — can run with T-06, T-08

---

### T-10 · Single-run entry point
**Spec refs**: all result-scraper + snapshot-storage requirements (integration)
**Description**: Implement `main.py` with three CLI modes via argparse: `--discover` (delegates to scripts/discover_api), `--once` (single fetch → parse → diff → store cycle), `--daemon` (starts scheduler). This wires together config → fetcher → differ → parser → storage in the correct order.
**Files**: `main.py`
**Dependencies**: T-06, T-07, T-08, T-09
**Complexity**: S
**Parallel**: NO — terminal integration task for Phase 2

---

## Phase 3 — Scheduler + Deployment

### T-11 · APScheduler daemon
**Spec refs**: scheduler/Configurable Interval Daemon (all four scenarios)
**Description**: Implement `scraper/scheduler.py` wrapping `main.py`'s `--once` logic in an APScheduler `BackgroundScheduler` + `IntervalTrigger`. Validates interval at startup ({5,10,15}), handles SIGTERM/SIGINT with `scheduler.shutdown(wait=True)` for graceful exit.
**Files**: `scraper/scheduler.py`
**Dependencies**: T-10
**Complexity**: M
**Parallel**: NO — needs T-10 complete

---

### T-12 · GitHub Actions cron workflow
**Spec refs**: design AD-04 — cloud fallback
**Description**: Create `.github/workflows/scraper.yml` with a `schedule: cron('*/10 * * * *')` trigger. Installs Python + dependencies, runs `python main.py --once`. Uses GitHub Secrets for ONPE_API_URL and other env vars.
**Files**: `.github/workflows/scraper.yml`
**Dependencies**: T-10 (main.py --once must be stable)
**Complexity**: S
**Parallel**: YES — can run with T-11

---

### T-13 · README
**Spec refs**: all domains — documentation of setup, discovery, running, queries
**Description**: Write `README.md` covering: prerequisites, `playwright install chromium`, running discovery, running once, running daemon, example SQLite dashboard queries for time-series analysis, and `.env.example` reference.
**Files**: `README.md`
**Dependencies**: T-10, T-11, T-12 (all runnable)
**Complexity**: S
**Parallel**: YES — can be drafted in parallel with T-11/T-12, finalized after

---

## Dependency Graph

```
T-01 ──┬──> T-03 ──> T-04 ──> T-05
       │         └──> T-07 (finalize)
       ├──> T-02 ──> T-07 (stubs)
       │         └──> T-09
       └──> T-06, T-08, T-09

T-06 ──┐
T-07 ──┼──> T-10 ──> T-11 ──> (daemon ready)
T-08 ──┤         └──> T-12
T-09 ──┘         └──> T-13

T-12, T-13 can run in parallel with T-11
```

## Parallel Batches

| Batch | Tasks          | Gate               |
|-------|----------------|--------------------|
| A     | T-01, T-02     | —                  |
| B     | T-03, T-04     | T-01 done          |
| C     | T-05, T-06, T-07 (stubs), T-08, T-09 | T-03 + T-04 done |
| D     | T-07 (finalize), T-10 | T-04 + Batch C done |
| E     | T-11, T-12, T-13 | T-10 done          |

---

## Review Workload Forecast

| Metric | Value |
|--------|-------|
| Estimated total changed lines | ~850–950 |
| Number of new files | 16 |
| Chained PRs recommended | **Yes** |
| 400-line budget risk | **High** |
| Decision needed before apply | **Yes** |

**Suggested PR splits**:
- PR-1: T-01 + T-02 + T-03 — scaffold + models + config (~140 lines)
- PR-2: T-04 + T-05 + T-06 + T-07 + T-08 + T-09 — scraper core (~550 lines; split at T-06/T-07 boundary if needed)
- PR-3: T-10 + T-11 + T-12 + T-13 — integration + deployment (~260 lines)
