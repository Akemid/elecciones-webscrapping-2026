"""
JSON response parser for the ONPE segunda vuelta API.

Parses two separate API responses per scrape cycle:
  - totales: /resumen-general/totales — actas % and vote totals
  - candidatos: /eleccion-presidencial/participantes-ubicacion-geografica-nombre
                — per-candidate vote counts and percentages

Real field names confirmed via network inspection on 2026-06-08.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from models.snapshot import Snapshot

logger = logging.getLogger(__name__)


class ParseError(ValueError):
    """Raised when required fields cannot be found in the API response."""


def _unwrap(payload: bytes, label: str) -> Any:
    """Decode bytes, parse JSON, and unwrap the 'data' key."""
    try:
        envelope: dict[str, Any] = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ParseError(f"{label}: not valid JSON — {exc}") from exc
    if not isinstance(envelope, dict) or "data" not in envelope:
        raise ParseError(f"{label}: expected {{success, data}} envelope, got {list(envelope.keys()) if isinstance(envelope, dict) else type(envelope).__name__}")
    return envelope["data"]


def parse_snapshot(
    totales_raw: bytes,
    candidatos_raw: bytes,
    scraped_at: str,
    response_hash: str,
) -> Snapshot:
    """Parse totales + candidatos API responses into a Snapshot.

    Args:
        totales_raw: Raw bytes from /resumen-general/totales.
        candidatos_raw: Raw bytes from /eleccion-presidencial/participantes-...
        scraped_at: ISO-8601 UTC timestamp (caller-supplied).
        response_hash: SHA-256 hex digest of combined raw bytes (caller-supplied).

    Returns:
        Snapshot with national-level data. regions list is empty (not available
        from these endpoints).

    Raises:
        ParseError: If JSON is malformed or required fields are missing.
    """
    totales: dict[str, Any] = _unwrap(totales_raw, "totales")
    candidatos: list[dict[str, Any]] = _unwrap(candidatos_raw, "candidatos")

    if not isinstance(totales, dict):
        raise ParseError(f"totales.data: expected dict, got {type(totales).__name__}")
    if not isinstance(candidatos, list) or len(candidatos) < 2:
        raise ParseError(f"candidatos.data: expected list of >=2 items, got {candidatos!r}")

    c1, c2 = candidatos[0], candidatos[1]

    logger.info(
        "Parsing: actas=%.2f%% | %s=%.3f%% | %s=%.3f%%",
        totales.get("actasContabilizadas", 0),
        c1.get("nombreCandidato", "?"),
        c1.get("porcentajeVotosValidos", 0),
        c2.get("nombreCandidato", "?"),
        c2.get("porcentajeVotosValidos", 0),
    )

    return Snapshot(
        scraped_at=scraped_at,
        response_hash=response_hash,
        actas_procesadas_pct=float(totales["actasContabilizadas"]),
        candidato_1_nombre=str(c1["nombreCandidato"]),
        candidato_1_votos=int(c1["totalVotosValidos"]),
        candidato_1_pct=float(c1["porcentajeVotosValidos"]),
        candidato_2_nombre=str(c2["nombreCandidato"]),
        candidato_2_votos=int(c2["totalVotosValidos"]),
        candidato_2_pct=float(c2["porcentajeVotosValidos"]),
        votos_blancos=0,   # not available in these endpoints
        votos_nulos=0,     # not available in these endpoints
        actas_total=int(totales["totalActas"]),
        regions=[],        # regional breakdown not yet available
    )
