"""
Data models for the ONPE segunda vuelta scraper.

These dataclasses represent the domain objects captured during each scrape cycle.
Field names on Snapshot and RegionResult are speculative until the API discovery
phase (T-04) runs and the real response shape is confirmed — see TODO comments.
"""

from dataclasses import dataclass, field


@dataclass
class RegionResult:
    """Per-departamento vote breakdown for a single snapshot.

    Fields map to the regional breakdown API response.
    TODO: verify field names against actual ONPE API response after discovery.
    """

    # TODO: confirm 'region_codigo' key in API response (could be 'codDepartamento' or similar)
    region_codigo: str
    region_nombre: str
    candidato_1_votos: int
    candidato_1_pct: float
    candidato_2_votos: int
    candidato_2_pct: float


@dataclass
class Snapshot:
    """National vote summary captured at a single point in time.

    All fields are required. `regions` defaults to an empty list and is
    populated separately after the regional breakdown fetch.

    TODO: verify all field-to-key mappings against actual ONPE API response after discovery.
    """

    scraped_at: str          # ISO-8601 UTC timestamp of the request
    response_hash: str       # SHA-256 hex digest of the raw response bytes
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
    regions: list[RegionResult] = field(default_factory=list)


@dataclass
class ChangeRecord:
    """Structured delta between two consecutive snapshots.

    Inserted into the `changes` SQLite table alongside the new snapshot.
    `snapshot_id` is a foreign key to the new snapshot's row.
    `prev_snapshot_id` references the prior snapshot row.
    """

    snapshot_id: int
    prev_snapshot_id: int
    delta_actas_pct: float
    delta_c1_votos: int
    delta_c2_votos: int
    detected_at: str         # ISO-8601 UTC; equals scraped_at of the new snapshot
