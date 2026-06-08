# Design: ONPE Segunda Vuelta Scraper

## Technical Approach

Greenfield Python scraper using a two-phase architecture: (1) Playwright-based API discovery runs once to capture ONPE backend URLs and headers, (2) httpx polling loop fetches results at configurable intervals with hash-based deduplication and dual-write storage (JSON snapshots + SQLite). APScheduler wraps the polling loop as a daemon; GitHub Actions cron provides a cloud fallback.

## Architecture Decisions

### AD-01: Scraping Strategy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Pure Playwright polling | Reliable but heavy: launches browser every cycle, ~200MB RAM, slow | Rejected |
| Pure httpx with guessed URLs | Lightweight but fragile: URL/headers unknown upfront, likely blocked | Rejected |
| **Playwright discovery + httpx polling** | Best of both: one-time browser cost, then lightweight HTTP polling | **Chosen** |

**Rationale**: ONPE's API URL is not publicly documented. Playwright intercepts network traffic once to discover the endpoint and required headers. All subsequent polling uses httpx with those captured headers, keeping resource usage minimal. Playwright-stealth is the fallback if httpx gets blocked.

### AD-02: Storage Strategy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| SQLite only | Queryable but not git-diffable, harder to audit raw data | Rejected |
| JSON only | Git-diffable audit trail but not queryable for time-series analysis | Rejected |
| **JSON snapshots + SQLite** | Dual-write: audit trail + queryable DB; minor write overhead | **Chosen** |
| Parquet | Overkill for ~200 snapshots over 48h; adds heavy dependency | Rejected |

**Rationale**: JSON snapshots provide immutable audit trail (one file per scrape). SQLite enables time-series queries and delta tracking. Both are file-based, portable, and require no external services.

### AD-03: Change Detection

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Deep field-by-field comparison | Expensive, complex, fragile to field ordering | Rejected |
| **SHA-256 hash of raw response** | Fast O(1) check, detects any change including whitespace | **Chosen** |
| Last-Modified / ETag headers | ONPE may not support these headers | Rejected |

**Rationale**: Hash the raw response body before parsing. Compare against the last stored hash. If identical, skip entirely (no parse, no write). If different, parse, store snapshot, compute structured delta via deepdiff for the `changes` table.

### AD-04: Scheduling

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `time.sleep` loop | Simple but no error recovery, no graceful shutdown | Rejected |
| **APScheduler IntervalTrigger** | Mature, handles missed jobs, graceful shutdown, configurable | **Chosen** |
| Celery / dramatiq | Requires Redis/RabbitMQ broker; massive overkill | Rejected |

**Rationale**: APScheduler's `BackgroundScheduler` with `IntervalTrigger` provides reliable scheduling with zero external dependencies. GitHub Actions `schedule` cron provides a free-tier cloud fallback that requires no infrastructure.

### AD-05: Configuration

**Choice**: `python-dotenv` + environment variables with typed `config.py` module.
**Alternatives considered**: pydantic-settings (heavier), argparse (not 12-factor friendly).
**Rationale**: Simple, 12-factor compatible. `.env` for local dev (gitignored), env vars for CI/cloud. Config module validates required vars at startup with clear error messages.

## Data Flow

```
[Playwright Discovery] ──one-time──→ .env (API_URL + headers)
                                        │
                                        ▼
                    ┌──────────── [Config] ◄── env vars
                    │
                    ▼
[APScheduler] ──interval──→ [Fetcher] ──httpx GET──→ ONPE API
                                │
                                ▼
                           [Differ] ──sha256──→ hash match? ──yes──→ skip (log)
                                │ no
                                ▼
                           [Parser] ──→ typed dataclasses
                                │
                        ┌───────┴───────┐
                        ▼               ▼
               [JSON Snapshot]    [SQLite Writer]
               data/snapshots/    data/election.db
               YYYY-MM-DD...json  snapshots + regions + changes
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `scraper/__init__.py` | Create | Package marker |
| `scraper/discover.py` | Create | Playwright network interceptor; captures API URL + headers to stdout/env |
| `scraper/fetcher.py` | Create | httpx client with retry (tenacity), stealth headers, Playwright fallback |
| `scraper/parser.py` | Create | Parse raw JSON response into `Snapshot` and `RegionResult` dataclasses |
| `scraper/storage.py` | Create | SQLite schema init + dual-write (JSON file + SQLite insert) |
| `scraper/differ.py` | Create | SHA-256 hash check + deepdiff delta computation for `changes` table |
| `scraper/scheduler.py` | Create | APScheduler BackgroundScheduler with IntervalTrigger + graceful shutdown |
| `models/__init__.py` | Create | Package marker |
| `models/snapshot.py` | Create | Dataclasses: `Snapshot`, `RegionResult`, `ChangeRecord` |
| `scripts/discover_api.py` | Create | CLI entry point for one-time Playwright discovery |
| `config.py` | Create | Load and validate env vars with defaults |
| `main.py` | Create | Entry point: `--discover`, `--once`, or `--daemon` modes |
| `pyproject.toml` | Create | Project metadata + dependencies |
| `.env.example` | Create | Template with all config vars documented |
| `.gitignore` | Create | Ignore `data/`, `.env`, `__pycache__/`, etc. |
| `.github/workflows/scraper.yml` | Create | GitHub Actions cron fallback (every 10 min) |

## Interfaces / Contracts

```python
# models/snapshot.py
@dataclass
class RegionResult:
    region_codigo: str
    region_nombre: str
    candidato_1_votos: int
    candidato_1_pct: float
    candidato_2_votos: int
    candidato_2_pct: float

@dataclass
class Snapshot:
    scraped_at: str              # ISO 8601
    response_hash: str           # SHA-256 hex
    actas_procesadas_pct: float
    candidato_1_nombre: str
    candidato_1_votos: int
    candidato_1_pct: float
    candidato_2_nombre: str
    candidato_2_votos: int
    candidato_2_pct: float
    votos_blancos: int
    votos_nulos: int
    actas_total: int
    regiones: list[RegionResult]

@dataclass
class ChangeRecord:
    snapshot_id: int
    prev_snapshot_id: int
    delta_actas_pct: float
    delta_c1_votos: int
    delta_c2_votos: int
    detected_at: str

# scraper/fetcher.py
async def fetch_results(config: Config) -> tuple[str, bytes]:
    """Returns (url_used, raw_response_bytes). Raises ScraperError on failure."""

# scraper/differ.py
def has_changed(raw_body: bytes, last_hash: str | None) -> tuple[bool, str]:
    """Returns (changed: bool, current_hash: str)."""

# scraper/storage.py
def save_snapshot(snapshot: Snapshot, raw_json: bytes, config: Config) -> int:
    """Dual-write: JSON file + SQLite. Returns snapshot_id."""
```

## SQLite Schema

Three tables: `snapshots` (national totals per scrape), `regions` (per-region breakdown linked to snapshot), `changes` (computed deltas between consecutive snapshots). Schema auto-created on first run via `storage.init_db()`. Foreign keys enforced.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `parser.py`, `differ.py`, `config.py` | pytest with fixture JSON payloads; no network |
| Unit | `storage.py` | pytest with in-memory SQLite (`:memory:`) |
| Integration | `fetcher.py` | pytest with `respx` (httpx mock); test retry + fallback logic |
| Integration | Full pipeline | pytest: fetch mock -> parse -> diff -> store; verify JSON + SQLite output |
| Manual | `discover.py` | Requires real browser + ONPE site; document manual test steps |

## Migration / Rollout

No migration required. Greenfield project. First run creates `data/` directory, SQLite schema, and initial snapshot. Rollback is trivial: delete `data/` to reset all state.

## Open Questions

- [ ] Exact ONPE API response shape unknown until discovery phase runs (blocking for parser field mapping)
- [ ] Whether ONPE uses anti-bot protections beyond User-Agent checks (affects fetcher fallback strategy)
