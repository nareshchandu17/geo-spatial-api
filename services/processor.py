"""Processing orchestration.

This module is the single entry-point the API calls into.  It accepts the
raw uploaded bytes + filename, validates them, reads the geospatial data,
extracts features, selects a metric CRS, computes measurements, persists
everything to SQLite, and returns the file id.

The flow is intentionally linear and synchronous, as the assignment
suggests:

    Upload -> Validate -> Read -> Detect CRS -> Extract features
         -> Select measurement CRS -> Compute measurements
         -> Persist -> Return API response

Errors raised by the validation / reading layer are ``GeoAPIError``
subclasses; the API translates them to HTTP responses.  Genuine unexpected
exceptions are caught here and re-raised as a 500-style error so we never
leak a stack trace.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS

import database as db
import config
from services import readers
from services.crs import select_measurement_crs, is_metric, to_metric_crs_or_none
from services.errors import (
    GeoAPIError,
    GeoprocessingError,
)
from services.measurements import measure_geometry, STATUS_UNAVAILABLE
from services.validation import (
    enforce_size,
    save_upload_to_temp,
    sniff_signature,
    validate_filename,
)


def process_upload(*, filename: str, content: bytes) -> dict[str, Any]:
    """Process a single upload end-to-end.  Returns the file-info dict."""
    # ---- 1. Validate the upload --------------------------------------------
    enforce_size(len(content))
    ext = validate_filename(filename)
    sniff_signature(content[:16], ext)

    # ---- 2. Persist the raw bytes to a temp path ---------------------------
    # Resolve at call time (not import time) so tests can override.
    data_dir = Path(str(config.DATA_DIR))
    tmp_root = data_dir / "uploads"
    tmp_root.mkdir(parents=True, exist_ok=True)
    upload_path = save_upload_to_temp(content, filename, ext, tmp_root)

    # ---- 3. Read the geospatial data ---------------------------------------
    try:
        if ext == ".zip":
            gdf, source_crs_str, read_warnings = readers.read_shapefile_zip(upload_path)
        else:  # .kml
            gdf, source_crs_str, read_warnings = readers.read_kml_file(upload_path)
    except GeoAPIError:
        # Re-raise without wrapping -- these are already nicely formatted.
        raise
    except Exception as exc:
        # Unknown / unexpected reader failure -> 422 not 500 by default,
        # because the most common cause is "the file is not really a
        # Shapefile/KML even though the magic bytes matched".
        raise GeoprocessingError(
            f"The uploaded file could not be processed: {exc}"
        ) from exc

    # ---- 4. Build pyproj CRS objects for downstream use -------------------
    src_crs_obj: CRS | None = None
    if source_crs_str:
        src_crs_obj = to_metric_crs_or_none(source_crs_str)
        if src_crs_obj is None:
            read_warnings.append(
                f"Source CRS '{source_crs_str}' is recorded but could not "
                "be parsed by pyproj."
            )

    # ---- 5. Select a measurement CRS --------------------------------------
    measurement_crs_obj, crs_warnings = select_measurement_crs(gdf, src_crs_obj)
    measurement_crs_str: str | None = None
    if measurement_crs_obj is not None:
        try:
            epsg = measurement_crs_obj.to_epsg()
        except Exception:
            epsg = None
        measurement_crs_str = (
            f"EPSG:{epsg}" if epsg else measurement_crs_obj.to_wkt()
        )

        # Final safety check before we trust it as "metric".
        if not is_metric(measurement_crs_obj):
            read_warnings.append(
                "Selected measurement CRS unit is not metres; "
                "measurements will be skipped where applicable."
            )
            measurement_crs_obj = None
            measurement_crs_str = None

    all_warnings = read_warnings + crs_warnings

    # ---- 6. Persist the file-level record ---------------------------------
    file_id = db.insert_file_record(
        filename=filename,
        feature_count=len(gdf),
        source_crs=source_crs_str,
        measurement_crs=measurement_crs_str,
        status="COMPLETED",
        warnings=all_warnings,
    )

    # ---- 7. Per-feature processing & persistence ---------------------------
    _process_features(
        gdf=gdf,
        file_id=file_id,
        source_crs_str=source_crs_str,
        source_crs_obj=src_crs_obj,
        measurement_crs_obj=measurement_crs_obj,
        crs_warnings=crs_warnings,
        read_warnings=read_warnings,
    )

    # ---- 8. Return the file-info dict -------------------------------------
    record = db.get_file_record(file_id)
    if record is None:  # pragma: no cover - shouldn't happen
        raise GeoprocessingError("Failed to read back the just-persisted file record.")
    return record


def _process_features(
    *,
    gdf: gpd.GeoDataFrame,
    file_id: str,
    source_crs_str: str | None,
    source_crs_obj: CRS | None,
    measurement_crs_obj: CRS | None,
    crs_warnings: list[str],
    read_warnings: list[str],
) -> None:
    """Measure every feature and persist each one."""
    for idx, row in enumerate(gdf.itertuples(index=False)):
        geom = row.geometry
        properties = getattr(row, "properties", None) or {}

        # GeoJSON geometry (with the original/source CRS preserved).
        try:
            geojson = _shapely_to_geojson(geom)
        except Exception:
            geojson = None

        try:
            measurements, status, feat_warnings = measure_geometry(
                geom, source_crs_obj, measurement_crs_obj
            )
        except Exception as exc:
            measurements, status, feat_warnings = {}, STATUS_UNAVAILABLE, [
                f"Measurement failed: {exc}"
            ]

        # If reprojection produced a per-feature warning, surface it.
        if crs_warnings and status == STATUS_UNAVAILABLE:
            feat_warnings = feat_warnings + [
                w for w in crs_warnings if "UTM zone" in w or "single UTM" in w
            ]

        db.insert_feature(
            file_id=file_id,
            feature_index=idx,
            geometry_type=getattr(geom, "geom_type", None),
            geometry_geojson=json.dumps(geojson) if geojson is not None else None,
            source_crs=source_crs_str,
            properties=_coerce_jsonable(properties),
            measurements=_coerce_jsonable(measurements),
            measurement_status=status,
            warnings=feat_warnings,
        )


def _shapely_to_geojson(geom: Any) -> dict[str, Any] | None:
    """Return a GeoJSON-compatible dict for *geom* (without CRS info)."""
    if geom is None:
        return None
    try:
        return geom.__geo_interface__
    except Exception:
        return None


def _coerce_jsonable(value: Any) -> Any:
    """Recursively convert numpy types to plain Python so json.dumps works."""
    import numpy as np
    if isinstance(value, dict):
        return {k: _coerce_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if f != f else f  # NaN -> None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float):
        return None if value != value else value
    return value


def get_measurements_response(file_id: str) -> dict[str, Any]:
    """Build the JSON response for ``GET /api/files/{id}/measurements/``."""
    record = db.get_file_record(file_id)
    if record is None:
        return None  # caller raises 404

    features = db.get_features(file_id)
    return {
        "file_id": record["id"],
        "filename": record["filename"],
        "feature_count": record["feature_count"],
        "source_crs": record["source_crs"],
        "measurement_crs": record["measurement_crs"],
        "features": features,
    }
