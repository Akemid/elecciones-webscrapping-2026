# ONPE Segunda Vuelta Scraper — Specification

## Purpose

Define the behavioral contract for a recurring scraper that captures Peru's ONPE presidential
runoff results (national summary + regional breakdown) into a time-series dataset. This is a
greenfield project; all requirements below are new.

---

## Domain: api-discovery

### Requirement: Network Interception Discovery

The discovery tool MUST launch a Playwright-controlled browser, navigate to the ONPE results
page, intercept all XHR/fetch network requests, and log any API endpoint URLs whose response
contains vote count or actas data. It SHALL output at least one candidate endpoint URL and its
required request headers to stdout and to a config file. It MUST NOT mutate any remote state.

#### Scenario: Successful discovery

- GIVEN the ONPE results page is reachable and the browser binary is available
- WHEN the discovery tool is executed
- THEN at least one API endpoint URL is captured from network traffic
- AND the URL and required headers are written to `.env` or `config.py`

#### Scenario: No XHR endpoints found — DOM fallback signal

- GIVEN the page loads but no XHR/fetch requests carry vote data
- WHEN the discovery tool finishes intercepting
- THEN the tool logs a warning that no REST endpoints were found
- AND exits with a non-zero code to signal manual intervention

#### Scenario: Browser binary missing

- GIVEN Playwright Chromium binary is not installed
- WHEN the discovery tool is executed
- THEN the tool exits with a clear error message referencing `playwright install chromium`

---

## Domain: result-scraper

### Requirement: National Summary Fetch

The scraper MUST fetch the national summary from the discovered ONPE API endpoint using
browser-like HTTP headers. The response MUST be parsed into a typed `Snapshot` containing:
`scraped_at` (ISO-8601), `actas_procesadas_pct`, `candidato_1_votos`, `candidato_1_pct`,
`candidato_2_votos`, `candidato_2_pct`, `votos_blancos`, `votos_nulos`, `actas_total`.

#### Scenario: Successful national fetch

- GIVEN the API endpoint is configured and reachable
- WHEN the scraper runs a scheduled cycle
- THEN a `Snapshot` with all nine fields populated is returned
- AND `scraped_at` is set to the UTC time of the request

#### Scenario: Playwright stealth fallback

- GIVEN the direct httpx request returns 403 or 429
- WHEN the scraper retries after exhausting httpx attempts
- THEN Playwright is used to navigate and extract the same data
- AND the resulting `Snapshot` is identical in structure

#### Scenario: Network failure with retries

- GIVEN the API is transiently unreachable
- WHEN each request attempt fails
- THEN the scraper retries up to 3 times with exponential backoff
- AND logs the attempt number and wait duration each time
- AND raises a terminal error after the third failure

### Requirement: Regional Breakdown Fetch

The scraper MUST fetch per-departamento results and parse them into a list of `RegionEntry`
records, each containing: `region_id`, `region_nombre`, `candidato_1_votos`, `candidato_1_pct`,
`candidato_2_votos`, `candidato_2_pct`. All 26 Peruvian departamentos MUST be present in
each snapshot.

#### Scenario: Full regional coverage

- GIVEN the API returns regional data
- WHEN the scraper parses the response
- THEN exactly 26 `RegionEntry` records are produced
- AND no region has null vote counts

#### Scenario: Partial regional data

- GIVEN the API returns fewer than 26 regions
- WHEN the scraper detects the missing count
- THEN it logs a warning with the missing region count
- AND still persists the partial data rather than discarding it

### Requirement: Scrape Duration Logging

The scraper MUST record the wall-clock duration of each full scrape cycle (national + regional)
and log it at INFO level. This allows interval tuning based on observed latency. Each run MUST
complete within 30 seconds; if it exceeds this threshold, the scraper MUST log a WARNING.

#### Scenario: Fast run

- GIVEN the API responds within normal latency
- WHEN the scrape cycle completes
- THEN duration is logged in the format `Scrape completed in {N}ms`

#### Scenario: Slow run threshold exceeded

- GIVEN the scrape cycle takes longer than 30 seconds
- WHEN the cycle ends
- THEN a WARNING is emitted: `Scrape exceeded 30s threshold ({N}ms)`

---

## Domain: snapshot-storage

### Requirement: Dual-Write Storage

The storage layer MUST write each new snapshot to both a JSON file and a SQLite row
atomically. The JSON filename MUST include the ISO-8601 UTC timestamp
(e.g., `snapshot_2026-06-08T14-30-00Z.json`). The SQLite `snapshots` table MUST contain
all `Snapshot` fields plus an auto-incremented `id`.

#### Scenario: New snapshot written

- GIVEN a `Snapshot` object with all fields populated
- WHEN the storage layer is called
- THEN a JSON file is created in the configured `data/` directory
- AND a row is inserted in the SQLite `snapshots` table

#### Scenario: JSON file naming

- GIVEN a snapshot with `scraped_at = "2026-06-08T14:30:00Z"`
- WHEN stored to disk
- THEN the file is named `snapshot_2026-06-08T14-30-00Z.json`

### Requirement: Hash-Based Deduplication

Before writing, the storage layer MUST compute `sha256(raw_response_bytes)`. If the hash
matches the previous snapshot's hash stored in SQLite, the write MUST be skipped entirely.
The scheduler MUST log that the snapshot was deduplicated.

#### Scenario: Duplicate snapshot skipped

- GIVEN the ONPE data has not changed since the last scrape
- WHEN the storage layer receives the new response
- THEN sha256 matches the stored hash
- AND no JSON file is written
- AND no SQLite row is inserted
- AND a log entry reads `Snapshot deduplicated — no new data`

#### Scenario: New data detected

- GIVEN the response hash differs from the previous stored hash
- WHEN the storage layer processes the snapshot
- THEN both JSON and SQLite writes proceed normally

### Requirement: Delta Computation and Storage

After each new (non-deduplicated) snapshot, the system MUST compute a structured `ChangeRecord`
containing: `snapshot_id` (FK to `snapshots`), `delta_actas_pct`, `delta_c1_votos`,
`delta_c2_votos`, `detected_at`. The `ChangeRecord` MUST be inserted into the SQLite `changes`
table in the same transaction as the snapshot row.

#### Scenario: Delta persisted with snapshot

- GIVEN a new snapshot differs from the previous one
- WHEN both are stored
- THEN a `ChangeRecord` is inserted with correct delta values
- AND `snapshot_id` references the new snapshot's `id`
- AND `detected_at` equals `scraped_at` of the new snapshot

#### Scenario: First snapshot — no delta

- GIVEN no prior snapshot exists in the database
- WHEN the first snapshot is stored
- THEN no `ChangeRecord` is created
- AND no error is raised

### Requirement: SQLite Query Performance

SQLite queries used to retrieve snapshots for dashboard or analysis MUST return results
in under 100 ms for datasets up to 200 snapshots. Required indexes: `snapshots(scraped_at)`,
`changes(snapshot_id)`.

#### Scenario: Time-range query performance

- GIVEN the `snapshots` table contains 200 rows
- WHEN a SELECT query filters by `scraped_at` range
- THEN results are returned in under 100 ms

---

## Domain: scheduler

### Requirement: Configurable Interval Daemon

The scheduler MUST run the scraper on a configurable interval. The interval MUST be set via
environment variable `SCRAPE_INTERVAL_MINUTES` with a default of 10 minutes. Supported values
are 5, 10, and 15 minutes. The daemon MUST handle `SIGTERM` and `SIGINT` gracefully, completing
any in-progress scrape before exiting.

#### Scenario: Daemon starts with default interval

- GIVEN `SCRAPE_INTERVAL_MINUTES` is not set
- WHEN the daemon starts
- THEN it runs the scraper every 10 minutes

#### Scenario: Custom interval via env var

- GIVEN `SCRAPE_INTERVAL_MINUTES=5`
- WHEN the daemon starts
- THEN it runs the scraper every 5 minutes

#### Scenario: Graceful shutdown

- GIVEN the daemon is running a scrape cycle
- WHEN SIGTERM is received
- THEN the current scrape completes
- AND the daemon exits with code 0

#### Scenario: Invalid interval value

- GIVEN `SCRAPE_INTERVAL_MINUTES=7`
- WHEN the daemon starts
- THEN it logs an error listing valid values (5, 10, 15)
- AND exits with a non-zero code

### Requirement: Configuration via Environment

All runtime configuration MUST be loadable from environment variables or a `.env` file.
No secrets or API endpoints SHALL be hardcoded in source files. Required variables:
`ONPE_API_URL`, `SCRAPE_INTERVAL_MINUTES`, `DATA_DIR`, `DB_PATH`.

#### Scenario: .env file loaded at startup

- GIVEN a `.env` file exists with `ONPE_API_URL` set
- WHEN the daemon starts
- THEN `ONPE_API_URL` is used for all requests
- AND no hardcoded URL is referenced

#### Scenario: Missing required variable

- GIVEN `ONPE_API_URL` is not set in env or `.env`
- WHEN the daemon starts
- THEN it raises a `ConfigurationError` naming the missing variable
- AND exits before attempting any network request

---

## Out of Scope

- Dashboard or visualization UI
- AWS Lambda / EventBridge / cloud deployment
- Per-distrito or per-mesa granularity
- WebSocket / SSE real-time streaming
- Historical backfill of already-missed snapshots
