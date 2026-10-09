"""Geometry measurements.

All measurements are computed on a **reprojected copy** of the source
geometry, never on the source geometry itself, and never on raw lon/lat
degrees.  See :mod:`services.crs` for the strategy.

Important rules
---------------

* **Point** geometries are not measurable.  We return an empty
  ``measurements`` dict and the status ``NOT_REQUIRED``.

* For **Polygon** and **MultiPolygon**, we report ``area_m2`` and
  ``area_km2``.

* For **LineString** and **MultiLineString``, we report ``length_m`` and
  ``length_km``.

* A measurement of exactly 0 (e.g. a degenerate polygon whose area is 0)
  is reported as the float ``0.0`` -- this is a real, finite value and is
  *not* the same as "could not calculate".

* When a measurement could not be computed (invalid geometry, no metric
  CRS, unsupported geometry type), the value is **omitted** from the
  measurements dict and a warning is added.

* NaN / infinity are never returned -- the conversion to JSON would produce
  invalid tokens.  We filter them out explicitly.
"""

from __future__ import annotations

import math
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

# Geom types we recognise for measurement purposes.
_POLYGON_TYPES = {"Polygon", "MultiPolygon"}
_LINE_TYPES = {"LineString", "MultiLineString", "LinearRing"}
_POINT_TYPES = {"Point", "MultiPoint"}

# Status values used by the API and stored in the database.
STATUS_COMPLETED = "COMPLETED"
STATUS_NOT_REQUIRED = "NOT_REQUIRED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_SKIPPED = "SKIPPED"


def geometry_type(geom: BaseGeometry | None) -> str | None:
    """Return the Shapely geometry type, or None for null geometries."""
    if geom is None:
        return None
    try:
        return geom.geom_type
    except Exception:
        return None


def measure_geometry(
    geom: BaseGeometry,
    source_crs: CRS | None,
    measurement_crs: CRS | None,
) -> tuple[dict[str, float], str, list[str]]:
    """Measure a single geometry.

    Returns ``(measurements, status, warnings)``.

    * ``measurements`` -- dict like ``{"area_m2": 12.3, "area_km2": ...}``
      (may be empty).
    * ``status`` -- one of ``COMPLETED``, ``NOT_REQUIRED``, ``UNAVAILABLE``.
    * ``warnings`` -- list of strings; e.g. invalid geometry, no metric CRS.
    """
    warnings: list[str] = []
    measurements: dict[str, float] = {}

    gtype = geometry_type(geom)

    if gtype is None:
        return measurements, STATUS_UNAVAILABLE, ["Geometry is null."]

    if gtype in _POINT_TYPES:
        return measurements, STATUS_NOT_REQUIRED, warnings

    if gtype not in _POLYGON_TYPES and gtype not in _LINE_TYPES:
        return measurements, STATUS_UNAVAILABLE, [
            f"Geometry type '{gtype}' is not supported for measurement."
        ]

    # Invalid geometry -> cannot measure.
    if not geom.is_valid:
        # Try to repair it with buffer(0) which fixes many common self-intersections.
        try:
            geom_fixed = geom.buffer(0)
        except Exception:
            geom_fixed = None
        if geom_fixed is None or geom_fixed.is_empty:
            return measurements, STATUS_UNAVAILABLE, [
                f"{gtype} is invalid and could not be repaired."
            ]
        geom = geom_fixed
        warnings.append(f"{gtype} was invalid; repaired with buffer(0).")

    # No metric CRS -> cannot measure safely.
    if measurement_crs is None:
        return measurements, STATUS_UNAVAILABLE, [
            "No metric measurement CRS is available for this feature; "
            "measurement skipped."
        ]

    # Reproject a copy into the metric CRS.
    try:
        if source_crs is None:
            # Shouldn't happen here -- caller validates upstream.
            return measurements, STATUS_UNAVAILABLE, [
                "Source CRS is missing; cannot reproject."
            ]
        geom_m = _reproject(geom, source_crs, measurement_crs)
        if geom_m is None:
            return measurements, STATUS_UNAVAILABLE, [
                "Could not build a coordinate transformation; "
                "measurement skipped."
            ]
    except Exception as exc:
        return measurements, STATUS_UNAVAILABLE, [
            f"Reprojection failed: {exc}"
        ]

    # Verify the measurement CRS is metric before labelling units.
    if measurement_crs is not None and not _crs_is_metric(measurement_crs):
        return measurements, STATUS_UNAVAILABLE, [
            f"Measurement CRS unit is not metres "
            f"({_unit_name(measurement_crs)}); measurements skipped."
        ]

    if gtype in _POLYGON_TYPES:
        try:
            area = float(geom_m.area)
        except Exception as exc:
            return measurements, STATUS_UNAVAILABLE, [f"Area calc failed: {exc}"]
        if not _is_finite(area):
            return measurements, STATUS_UNAVAILABLE, ["Area is not a finite number."]
        measurements["area_m2"] = area
        measurements["area_km2"] = area / 1_000_000.0
        return measurements, STATUS_COMPLETED, warnings

    if gtype in _LINE_TYPES:
        try:
            length = float(geom_m.length)
        except Exception as exc:
            return measurements, STATUS_UNAVAILABLE, [f"Length calc failed: {exc}"]
        if not _is_finite(length):
            return measurements, STATUS_UNAVAILABLE, ["Length is not a finite number."]
        measurements["length_m"] = length
        measurements["length_km"] = length / 1_000.0
        return measurements, STATUS_COMPLETED, warnings

    return measurements, STATUS_UNAVAILABLE, [f"Geometry type {gtype} not measurable."]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _reproject(geom: BaseGeometry, src: CRS, dst: CRS):
    """Return *geom* reprojected from *src* to *dst*.

    Uses ``shapely.ops.transform`` to apply the pyproj ``Transformer.transform``
    callable to every coordinate of the geometry.  Returns ``None`` if the
    transformer cannot be constructed.

    The source geometry is never modified -- ``shapely.ops.transform``
    returns a new geometry.
    """
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer
    try:
        transformer = Transformer.from_crs(src, dst, always_xy=True)
    except Exception:
        return None
    return shp_transform(transformer.transform, geom)


def _transformer(src: CRS, dst: CRS):
    """Deprecated: kept for backwards-compat.  Use :func:`_reproject`."""
    return None


def _crs_is_metric(crs: CRS) -> bool:
    """True if the CRS's linear unit is the metre (or a synonym)."""
    try:
        for ax in crs.axis_info:
            unit = (ax.unit_name or "").lower()
            if any(m in unit for m in ("metre", "meter")):
                return True
            # foot / ft / ... are NOT metres.
            if any(f in unit for f in ("foot", "ft", "yard", "chain", "mile", "link", "nautical")):
                return False
    except Exception:
        pass
    return False


def _unit_name(crs: CRS) -> str:
    """Best-effort unit name for warnings."""
    try:
        for ax in crs.axis_info:
            if ax.unit_name:
                return ax.unit_name
    except Exception:
        pass
    return "unknown"


def _is_finite(value: Any) -> bool:
    """True if *value* is a finite number (not NaN, not infinity)."""
    try:
        return bool(math.isfinite(float(value)))
    except Exception:
        return False
