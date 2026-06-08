"""Basic smoke tests for the ONPE scraper components."""
import pytest
from unittest.mock import MagicMock, patch
from models.snapshot import Snapshot, RegionResult, ChangeRecord
from scraper.differ import compute_hash, has_changed


def test_compute_hash_consistent():
    """Same input always produces same hash."""
    data = b'{"test": 1}'
    assert compute_hash(data) == compute_hash(data)


def test_compute_hash_differs():
    """Different input produces different hash."""
    assert compute_hash(b'{"a": 1}') != compute_hash(b'{"b": 2}')


def test_has_changed_no_storage():
    """has_changed returns True when no previous hash exists."""
    mock_storage = MagicMock()
    mock_storage.get_last_hash.return_value = None
    assert has_changed(b'data', mock_storage) is True


def test_has_changed_same_hash():
    """has_changed returns False when hash matches previous."""
    data = b'same data'
    mock_storage = MagicMock()
    mock_storage.get_last_hash.return_value = compute_hash(data)
    assert has_changed(data, mock_storage) is False


def test_has_changed_different_hash():
    """has_changed returns True when hash differs from previous."""
    mock_storage = MagicMock()
    mock_storage.get_last_hash.return_value = compute_hash(b'old data')
    assert has_changed(b'new data', mock_storage) is True


def test_snapshot_dataclass_fields():
    """Snapshot dataclass has required fields."""
    s = Snapshot(
        scraped_at="2026-06-08T10:00:00Z",
        response_hash="abc123",
        actas_procesadas_pct=92.5,
        candidato_1_nombre="Candidato A",
        candidato_1_votos=5000000,
        candidato_1_pct=51.3,
        candidato_2_nombre="Candidato B",
        candidato_2_votos=4750000,
        candidato_2_pct=48.7,
        votos_blancos=50000,
        votos_nulos=30000,
        actas_total=92766,
    )
    assert s.actas_procesadas_pct == 92.5
    assert len(s.regions) == 0


def test_region_result_dataclass():
    """RegionResult dataclass has required fields."""
    r = RegionResult(
        region_codigo="15",
        region_nombre="Lima",
        candidato_1_votos=2000000,
        candidato_1_pct=52.0,
        candidato_2_votos=1850000,
        candidato_2_pct=48.0,
    )
    assert r.region_nombre == "Lima"


def test_change_record_dataclass():
    """ChangeRecord dataclass has required fields."""
    c = ChangeRecord(
        snapshot_id=2,
        prev_snapshot_id=1,
        delta_actas_pct=0.5,
        delta_c1_votos=10000,
        delta_c2_votos=8000,
        detected_at="2026-06-08T10:10:00Z",
    )
    assert c.delta_actas_pct == 0.5
