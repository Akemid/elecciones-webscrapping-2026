"""
Hash-based deduplication and delta computation for the ONPE scraper.

Two responsibilities:
  1. Deduplication — compute SHA-256 of the raw response and compare against
     the last stored hash to avoid redundant writes.
  2. Delta computation — once a new snapshot is confirmed as different,
     compute structured deltas (ChangeRecord) for the changes table.
"""

from __future__ import annotations

import hashlib
import logging

from models.snapshot import ChangeRecord, Snapshot
from scraper.storage import Storage

logger = logging.getLogger(__name__)


def compute_hash(raw: bytes) -> str:
    """Return the SHA-256 hex digest of the given bytes.

    Args:
        raw: Raw HTTP response body.

    Returns:
        Lowercase hex string (64 characters).
    """
    return hashlib.sha256(raw).hexdigest()


def has_changed(raw: bytes, storage: Storage) -> bool:
    """Return True if the hash of raw differs from the last stored hash.

    If the hashes match, logs ``Snapshot deduplicated — no new data`` and
    returns False. A return value of False means the caller should skip
    parsing and writing entirely.

    Args:
        raw: Raw response bytes from the current fetch.
        storage: Initialised Storage instance used to look up the last hash.

    Returns:
        True if the response is new (hashes differ or no prior snapshot).
        False if the response is identical to the last stored one.
    """
    current_hash = compute_hash(raw)
    last_hash = storage.get_last_hash()

    if last_hash is not None and current_hash == last_hash:
        logger.info("Snapshot deduplicated — no new data")
        return False

    logger.debug("Hash changed: prev=%s current=%s", last_hash, current_hash)
    return True


def get_prev_snapshot(storage: Storage) -> Snapshot | None:
    """Fetch the most recent stored Snapshot for delta computation.

    Args:
        storage: Initialised Storage instance.

    Returns:
        The last Snapshot, or None if the database is empty (first run).
    """
    return storage.get_last_snapshot()


def compute_delta(
    current: Snapshot,
    prev_snapshot_id: int,
    storage: Storage,
) -> ChangeRecord:
    """Compute a ChangeRecord from the current snapshot vs the previous one.

    Retrieves the last stored snapshot from storage and computes arithmetic
    deltas for the three tracked fields. Uses simple subtraction rather
    than deepdiff because the fields of interest are scalar numerics.

    Args:
        current: The newly parsed Snapshot (not yet written to DB — its
            snapshot_id must be supplied separately after saving).
        prev_snapshot_id: The DB id of the prior snapshot row. Used as the
            foreign key reference in the ChangeRecord (not used to fetch
            the snapshot — this function always diffs against the latest
            stored row, which is the same row when called before saving
            ``current``).
        storage: Initialised Storage instance (used to retrieve prev data).

    Returns:
        A ChangeRecord with computed deltas. snapshot_id is set to -1 as
        a sentinel — the caller MUST update it with the real DB id after
        calling storage.save_snapshot().
    """
    prev = storage.get_last_snapshot()

    if prev is None:
        # Edge case: caller should guard against this, but return a zero-delta
        # ChangeRecord rather than crashing.
        logger.warning("compute_delta called with no prior snapshot; returning zero deltas")
        return ChangeRecord(
            snapshot_id=-1,
            prev_snapshot_id=prev_snapshot_id,
            delta_actas_pct=0.0,
            delta_c1_votos=0,
            delta_c2_votos=0,
            detected_at=current.scraped_at,
        )

    delta_actas = current.actas_procesadas_pct - prev.actas_procesadas_pct
    delta_c1 = current.candidato_1_votos - prev.candidato_1_votos
    delta_c2 = current.candidato_2_votos - prev.candidato_2_votos

    logger.info(
        "Delta computed: actas=+%.4f%% c1_votos=+%d c2_votos=+%d",
        delta_actas,
        delta_c1,
        delta_c2,
    )

    return ChangeRecord(
        snapshot_id=-1,  # sentinel — caller must replace with real snapshot_id
        prev_snapshot_id=prev_snapshot_id,
        delta_actas_pct=delta_actas,
        delta_c1_votos=delta_c1,
        delta_c2_votos=delta_c2,
        detected_at=current.scraped_at,
    )
