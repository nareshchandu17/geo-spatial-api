"""SQLite database layer.

The module exposes a small, dependency-free persistence API used by the
service layer:

* :func:`init_db`           -- create the schema (idempotent).
* :func:`get_connection`    -- return a configured ``sqlite3.Connection``.
* :func:`insert_file_record` -- persist a processed file's metadata.
* :func:`get_file_record`   -- fetch a single file record by id.
* :func:`insert_feature`    -- persist a single feature row.
* :func:`get_features`      -- list features for a file id.

Parameterized SQL is used everywhere; no string interpolation of user input
ever reaches a query.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from config import DATABASE_PATH

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS files (
    id              TEXT    PRIMARY KEY,
    filename        TEXT    NOT NULL,
    feature_count   INTEGER NOT NULL,
    source_crs      TEXT,
    measurement_crs TEXT,
    status          TEXT    NOT NULL,
    warnings        TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS features (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             TEXT    NOT NULL,
    feature_index       INTEGER NOT NULL,
    geometry_type       TEXT,
    geometry_geojson    TEXT,
    source_crs          TEXT,
    properties_json     TEXT    NOT NULL DEFAULT '{}',
    measurements_json   TEXT    NOT NULL DEFAULT '{}',
    measurement_status  TEXT    NOT NULL,
    warnings_json       TEXT    NOT NULL DEFAULT '[]',
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_features_file_id ON features(file_id);
"""


# --------------------------------------------------------------------------- #
# Connection helper
# --------------------------------------------------------------------------- #

def get_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection.

    * ``row_factory = Row`` so callers can address columns by name.
    * ``foreign_keys = ON`` so cascade deletes work.
    """
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the schema if it does not already exist."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


# --------------------------------------------------------------------------- #
# File records
# --------------------------------------------------------------------------- #

def insert_file_record(
    *,
    filename: str,
    feature_count: int,
    source_crs: str | None,
    measurement_crs: str | None,
    status: str,
    warnings: list[str] | None = None,
    file_id: str | None = None,
    created_at: str | None = None,
) -> str:
    """Persist a processed file's metadata and return the generated id."""
    file_id = file_id or uuid.uuid4().hex
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    warnings = warnings or []

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO files
                (id, filename, feature_count, source_crs, measurement_crs,
                 status, warnings, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                filename,
                feature_count,
                source_crs,
                measurement_crs,
                status,
                json.dumps(warnings),
                created_at,
            ),
        )
        conn.commit()
    return file_id


def get_file_record(file_id: str) -> dict[str, Any] | None:
    """Return the file record as a dict, or ``None`` when not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()

    if row is None:
        return None

    return _file_row_to_dict(row)


def list_file_records() -> list[dict[str, Any]]:
    """Return all file records (newest first)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM files ORDER BY created_at DESC"
        ).fetchall()
    return [_file_row_to_dict(r) for r in rows]


def _file_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "feature_count": row["feature_count"],
        "source_crs": row["source_crs"],
        "crs": row["source_crs"],  # convenience alias used by the API
        "measurement_crs": row["measurement_crs"],
        "status": row["status"],
        "warnings": json.loads(row["warnings"]),
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- #
# Feature records
# --------------------------------------------------------------------------- #

def insert_feature(
    *,
    file_id: str,
    feature_index: int,
    geometry_type: str | None,
    geometry_geojson: str | None,
    source_crs: str | None,
    properties: dict[str, Any] | None,
    measurements: dict[str, Any] | None,
    measurement_status: str,
    warnings: list[str] | None,
) -> None:
    measurements = measurements or {}
    properties = properties or {}
    warnings = warnings or []

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO features
                (file_id, feature_index, geometry_type, geometry_geojson,
                 source_crs, properties_json, measurements_json,
                 measurement_status, warnings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                feature_index,
                geometry_type,
                geometry_geojson,
                source_crs,
                json.dumps(properties),
                json.dumps(measurements),
                measurement_status,
                json.dumps(warnings),
            ),
        )
        conn.commit()


def get_features(file_id: str) -> list[dict[str, Any]]:
    """Return all features for a file id, ordered by ``feature_index``."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM features WHERE file_id = ? ORDER BY feature_index ASC",
            (file_id,),
        ).fetchall()

    return [_feature_row_to_dict(r) for r in rows]


def _feature_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "feature_index": row["feature_index"],
        "geometry_type": row["geometry_type"],
        "geometry": json.loads(row["geometry_geojson"]) if row["geometry_geojson"] else None,
        "crs": row["source_crs"],
        "properties": json.loads(row["properties_json"]),
        "measurements": json.loads(row["measurements_json"]),
        "measurement_status": row["measurement_status"],
        "warnings": json.loads(row["warnings_json"]),
    }


def has_features(file_id: str) -> bool:
    """Cheap check used by the API to detect unknown ids early."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM features WHERE file_id = ? LIMIT 1",
            (file_id,),
        ).fetchone()
    return row is not None
