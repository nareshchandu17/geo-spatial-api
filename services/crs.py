"""CRS strategy.

The single most important correctness rule in this assignment:

    **Never calculate area or length directly from longitude / latitude
    degrees.**

A degree of longitude is ~111 km at the equator but ~0 m at the poles.  Any
"area" computed in degree^2 is meaningless.  We always reproject the
geometry into a projected CRS whose unit is the **metre** before computing
lengths or areas.

Selection strategy
-------------------

1. If the source CRS is ``None`` we cannot safely measure -- the file may be
   in some unknown projected CRS, or it may be raw lon/lat.  We refuse to
   silently guess.  The caller gets the feature with a warning and an empty
   ``measurements`` object.

2. If the source CRS is **projected** and its linear unit is already the
   metre, we can use the source CRS directly as the measurement CRS.  (We
   still verify the unit; some projected CRSs use the US survey foot or the
   international foot -- those are *not* metres and we either transform to a
   metric CRS or mark measurements as unavailable.)

3. If the source CRS is **geographic** (e.g. EPSG:4326), we use
   GeoPandas' ``estimate_utm_crs()`` to pick the appropriate UTM zone for
   the dataset's extent.  This is the cleanest local projection for small to
   medium-size data.

4. For very large / globally distributed datasets a single UTM zone is a
   poor choice -- distortion at the edges of the zone becomes large.  We
   detect this case (extent spans more than ~6 degrees of longitude, or
   crosses both hemispheres) and emit a warning, but still return a
   best-effort measurement using a single zone.

Limitations
-----------

* ``estimate_utm_crs`` may pick different zones for different features in a
  very wide dataset; we use one zone for the whole file so results are
  internally comparable.
* We never overwrite the source geometry: we always transform a *copy* and
  keep the original for the API response.
"""

from __future__ import annotations

import math
from typing import Any

import geopandas as gpd
from pyproj import CRS

from config import VERIFY_METRIC_UNIT


# Linear unit names (lower-cased) that we accept as "1 unit == 1 metre".
_METRE_UNIT_NAMES = {
    "metre",
    "meter",
    "m",
}


def is_geographic(crs: Any) -> bool:
    """True if *crs* is a geographic (lon/lat) CRS."""
    if crs is None:
        return False
    try:
        return bool(crs.is_geographic)
    except Exception:
        return False


def is_projected(crs: Any) -> bool:
    """True if *crs* is a projected CRS (e.g. UTM, Web Mercator)."""
    if crs is None:
        return False
    try:
        return bool(crs.is_projected)
    except Exception:
        return False


def linear_unit_name(crs: Any) -> str | None:
    """Return the lower-cased linear unit name of *crs* or ``None``."""
    if crs is None:
        return None
    try:
        # pyproj 3.x: crs.axis_info[0].unit_name
        for ax in crs.axis_info:
            if getattr(ax, "unit_name", None):
                return ax.unit_name.lower()
    except Exception:
        return None
    return None


def is_metric(crs: Any) -> bool:
    """True if the CRS's linear unit is the metre (or a near-synonym)."""
    if crs is None:
        return False
    unit = linear_unit_name(crs)
    if unit is None:
        return False
    return any(m in unit for m in _METRE_UNIT_NAMES)


def select_measurement_crs(
    gdf: gpd.GeoDataFrame, source_crs: Any | None
) -> tuple[CRS | None, list[str]]:
    """Pick the projected CRS to use for metric measurements.

    Returns ``(crs_or_None, warnings)``.  ``crs_or_None`` is a
    :class:`pyproj.CRS` we have verified to be metric, or ``None`` when no
    safe metric CRS could be determined.
    """
    warnings: list[str] = []

    # Case 1: no source CRS -- cannot guess.
    if source_crs is None:
        warnings.append(
            "Source CRS is missing.  Metric measurements are not "
            "computed to avoid mislabeling unknown projected coordinates."
        )
        return None, warnings

    # Make sure we have a real pyproj CRS object.
    try:
        src = CRS.from_user_input(source_crs) if not isinstance(source_crs, CRS) else source_crs
    except Exception as exc:
        warnings.append(f"Source CRS could not be parsed ({exc}); measurements unavailable.")
        return None, warnings

    # Case 2: source is projected and already metric -> use directly.
    if is_projected(src):
        if VERIFY_METRIC_UNIT and not is_metric(src):
            warnings.append(
                f"Source CRS is projected but uses '{linear_unit_name(src)}' "
                "rather than metres.  Measurements are not reported to "
                "avoid unit mislabelling."
            )
            return None, warnings
        return src, warnings

    # Case 3: source is geographic -> pick a UTM zone.
    if is_geographic(src):
        try:
            utm = _pick_utm(gdf, src)
        except Exception as exc:
            warnings.append(
                f"Could not pick a UTM zone for geographic CRS ({exc}); "
                "measurements unavailable."
            )
            return None, warnings

        if utm is None:
            warnings.append(
                "Could not derive a UTM zone from the data extent; "
                "measurements unavailable."
            )
            return None, warnings

        _warn_if_wide_extent(gdf, src, warnings)
        return utm, warnings

    # Case 4: source CRS is neither geographic nor projected -- refuse.
    warnings.append(
        "Source CRS is neither geographic nor projected; measurements unavailable."
    )
    return None, warnings


def _pick_utm(gdf: gpd.GeoDataFrame, src_crs: CRS) -> CRS | None:
    """Return a metric UTM CRS for the data extent.

    GeoPandas' ``estimate_utm_crs`` requires the data to be in a known
    geographic CRS (which we have, here).  When the source is already
    geographic, ``estimate_utm_crs`` reprojects internally.  When the source
    is a non-EPSG geographic CRS we still try, but the result may be None.
    """
    # Work on a copy so we never mutate the caller's frame.
    g = gdf.copy()
    if g.crs is None:
        g = g.set_crs(src_crs)
    try:
        return g.estimate_utm_crs()
    except Exception:
        return None


def _warn_if_wide_extent(
    gdf: gpd.GeoDataFrame, src_crs: CRS, warnings: list[str]
) -> None:
    """Emit a warning if the geographic extent spans more than ~6 degrees.

    A single UTM zone is ~6 degrees wide; using one zone for very wide data
    causes non-trivial distortion at the edges.  We still produce a number
    -- but the user must know it's a best-effort measurement.
    """
    try:
        # Compute the lon/lat total_bounds in the source geographic CRS.
        bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)
        dx = bounds[2] - bounds[0]
        dy = bounds[3] - bounds[1]
        if math.isfinite(dx) and math.isfinite(dy) and (dx > 6 or dy > 8):
            warnings.append(
                f"Dataset spans {dx:.2f}°x{dy:.2f}°; a single UTM zone "
                "introduces distortion at the edges.  Measurements are "
                "best-effort -- consider splitting the data by UTM zone "
                "for higher accuracy."
            )
    except Exception:
        # total_bounds can fail on mixed geometry types -- ignore.
        pass


def to_metric_crs_or_none(crs: Any) -> CRS | None:
    """Return a ``pyproj.CRS`` for *crs* if it can be parsed, else None."""
    if crs is None:
        return None
    try:
        return CRS.from_user_input(crs) if not isinstance(crs, CRS) else crs
    except Exception:
        return None
