"""
Dual-write storage layer for the ONPE segunda vuelta scraper.

Persists each new Snapshot to both:
  - A JSON file under data/snapshots/ (immutable audit trail)
  - SQLite rows in election.db (queryable time-series)

See scraper/_schema.py for the full DDL.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from config import Config
from models.snapshot import ChangeRecord, RegionResult, Snapshot
from scraper._schema import ALL_DDL

logger = logging.getLogger(__name__)

_SNAPSHOTS_SUBDIR = "snapshots"


class Storage:
    """Manages dual-write persistence (JSON files + SQLite) for snapshots."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._data_dir = Path(config.data_dir)
        # config.db_path is always resolved in load_config() — never empty.
        self._db_path = Path(config.db_path)
        self._snapshots_dir = self._data_dir / _SNAPSHOTS_SUBDIR

    def init_db(self) -> None:
        """Create directory tree and SQLite schema if not present."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            for stmt in ALL_DDL:
                conn.execute(stmt)
            conn.commit()
        logger.info("Storage initialised: db=%s", self._db_path)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> int:
        """Insert snapshot into SQLite; return the new snapshot id."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots (
                    scraped_at, response_hash, actas_procesadas_pct,
                    candidato_1_nombre, candidato_1_votos, candidato_1_pct,
                    candidato_2_nombre, candidato_2_votos, candidato_2_pct,
                    votos_blancos, votos_nulos, actas_total
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.scraped_at, snapshot.response_hash,
                    snapshot.actas_procesadas_pct,
                    snapshot.candidato_1_nombre, snapshot.candidato_1_votos,
                    snapshot.candidato_1_pct,
                    snapshot.candidato_2_nombre, snapshot.candidato_2_votos,
                    snapshot.candidato_2_pct,
                    snapshot.votos_blancos, snapshot.votos_nulos, snapshot.actas_total,
                ),
            )
            snapshot_id: int = cursor.lastrowid  # type: ignore[assignment]
            _insert_regions(conn, snapshot_id, snapshot.regions)
            conn.commit()
        logger.info("Snapshot saved: id=%d at=%s", snapshot_id, snapshot.scraped_at)
        return snapshot_id

    def save_change(self, change: ChangeRecord) -> None:
        """Insert a ChangeRecord into the changes table."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO changes (
                    snapshot_id, prev_snapshot_id, delta_actas_pct,
                    delta_c1_votos, delta_c2_votos, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    change.snapshot_id, change.prev_snapshot_id,
                    change.delta_actas_pct, change.delta_c1_votos,
                    change.delta_c2_votos, change.detected_at,
                ),
            )
            conn.commit()
        logger.info("Change saved: snapshot_id=%d delta_actas=%.4f", change.snapshot_id, change.delta_actas_pct)

    def write_json(self, snapshot: Snapshot, raw: bytes) -> Path:
        """Write raw bytes to data/snapshots/snapshot_<safe-timestamp>.json."""
        safe_ts = snapshot.scraped_at.replace(":", "-").replace(" ", "T")
        dest = self._snapshots_dir / f"snapshot_{safe_ts}.json"
        dest.write_bytes(raw)
        logger.info("Snapshot JSON written: %s", dest)
        return dest

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_last_hash(self) -> str | None:
        """Return the response_hash of the most recent snapshot, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_hash FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None

    def get_last_snapshot_id(self) -> int | None:
        """Return the id of the most recent snapshot row, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None

    def get_last_snapshot(self) -> Snapshot | None:
        """Return the most recent stored Snapshot including regions, or None."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, scraped_at, response_hash, actas_procesadas_pct,
                       candidato_1_nombre, candidato_1_votos, candidato_1_pct,
                       candidato_2_nombre, candidato_2_votos, candidato_2_pct,
                       votos_blancos, votos_nulos, actas_total
                FROM snapshots ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            region_rows = conn.execute(
                """
                SELECT region_codigo, region_nombre,
                       candidato_1_votos, candidato_1_pct,
                       candidato_2_votos, candidato_2_pct
                FROM regions WHERE snapshot_id = ?
                """,
                (row[0],),
            ).fetchall()

        return Snapshot(
            scraped_at=row[1], response_hash=row[2], actas_procesadas_pct=row[3],
            candidato_1_nombre=row[4], candidato_1_votos=row[5], candidato_1_pct=row[6],
            candidato_2_nombre=row[7], candidato_2_votos=row[8], candidato_2_pct=row[9],
            votos_blancos=row[10], votos_nulos=row[11], actas_total=row[12],
            regions=[
                RegionResult(r[0], r[1], r[2], r[3], r[4], r[5]) for r in region_rows
            ],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _insert_regions(
    conn: sqlite3.Connection, snapshot_id: int, regions: list[RegionResult]
) -> None:
    conn.executemany(
        """
        INSERT INTO regions (
            snapshot_id, region_codigo, region_nombre,
            candidato_1_votos, candidato_1_pct,
            candidato_2_votos, candidato_2_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (snapshot_id, r.region_codigo, r.region_nombre,
             r.candidato_1_votos, r.candidato_1_pct,
             r.candidato_2_votos, r.candidato_2_pct)
            for r in regions
        ],
    )
