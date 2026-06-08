"""
SQLite DDL statements for the ONPE scraper database.

Imported by scraper/storage.py. Kept separate to avoid inflating storage.py
past the 150-line ceiling.
"""

CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_at TEXT NOT NULL,
    response_hash TEXT NOT NULL UNIQUE,
    actas_procesadas_pct REAL,
    candidato_1_nombre TEXT,
    candidato_1_votos INTEGER,
    candidato_1_pct REAL,
    candidato_2_nombre TEXT,
    candidato_2_votos INTEGER,
    candidato_2_pct REAL,
    votos_blancos INTEGER,
    votos_nulos INTEGER,
    actas_total INTEGER
);
"""

CREATE_REGIONS = """
CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER REFERENCES snapshots(id),
    region_codigo TEXT,
    region_nombre TEXT,
    candidato_1_votos INTEGER,
    candidato_1_pct REAL,
    candidato_2_votos INTEGER,
    candidato_2_pct REAL
);
"""

CREATE_CHANGES = """
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER REFERENCES snapshots(id),
    prev_snapshot_id INTEGER REFERENCES snapshots(id),
    delta_actas_pct REAL,
    delta_c1_votos INTEGER,
    delta_c2_votos INTEGER,
    detected_at TEXT NOT NULL
);
"""

INDEX_SCRAPED_AT = (
    "CREATE INDEX IF NOT EXISTS idx_snapshots_scraped_at ON snapshots(scraped_at);"
)
INDEX_CHANGES_SNAPSHOT = (
    "CREATE INDEX IF NOT EXISTS idx_changes_snapshot_id ON changes(snapshot_id);"
)

ALL_DDL = [CREATE_SNAPSHOTS, CREATE_REGIONS, CREATE_CHANGES, INDEX_SCRAPED_AT, INDEX_CHANGES_SNAPSHOT]
