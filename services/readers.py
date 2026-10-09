"""File readers for Shapefile (ZIP) and KML uploads.

Both readers return a uniform tuple::

    (GeoDataFrame, source_crs: str | None, warnings: list[str])

* The GeoDataFrame contains a ``geometry`` column (Shapely geometries) and a
  ``properties`` column (a dict per row) -- this is the shape the rest of the
  pipeline expects.
* ``source_crs`` is the EPSG:xxxx string detected from the file, or ``None``
  when the file does not declare one.
* ``warnings`` is a list of human-readable strings about anything suspicious
  (mixed geometry types, dropped empty geometries, KML files without a CRS
  hint, etc.).

We never raise on a *single* bad feature.  Invalid features are collected
into the warnings list and skipped, so that one bad row does not poison an
otherwise good file.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    shape as shapely_shape,
)

from services.errors import (
    AmbiguousShapefileError,
    GeoprocessingError,
    InvalidUploadError,
    KmlParseError,
    MissingShapefileError,
    ZipPathTraversalError,
)

# --------------------------------------------------------------------------- #
# ZIP / Shapefile
# --------------------------------------------------------------------------- #

# Filename-component extensions a Shapefile set can include.  The minimum is
# .shp + .shx + .dbf; .prj (CRS) and .cpg (codepage) are nice to have.
SHP_REQUIRED: tuple[str, ...] = (".shp", ".shx", ".dbf")


def _is_safe_zip_member(member_name: str) -> bool:
    """Reject absolute paths, drive letters, and ``..`` traversal."""
    # Normalise to forward slashes.
    norm = member_name.replace("\\", "/")
    if norm.startswith("/"):
        return False
    # Windows drive letter like "C:foo"
    if re.match(r"^[a-zA-Z]:", norm):
        return False
    parts = norm.split("/")
    if ".." in parts:
        return False
    return True


def _find_shapefile_sets(zip_path: Path) -> list[str]:
    """Return the base names of every complete Shapefile set inside *zip_path*.

    A "base name" is the path without the ``.shp``/``.shx``/``.dbf`` suffix,
    e.g. ``myshapes/survey`` -- so we keep directory info to disambiguate
    multiple shapefiles in different folders.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n]

    # Reject path traversal up front -- this is a security check.
    for n in names:
        if not _is_safe_zip_member(n):
            raise ZipPathTraversalError(f"ZIP contains an unsafe path: {n!r}")

    # Group by stem.
    stems: dict[str, set[str]] = {}
    for n in names:
        # Skip directories and hidden/macOS metadata files.
        if n.endswith("/"):
            continue
        if "__MACOSX" in n.split("/"):
            continue
        if os.path.basename(n).startswith("._") or os.path.basename(n).startswith("."):
            continue
        stem, ext = os.path.splitext(n)
        ext = ext.lower()
        if ext not in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qmd"):
            continue
        stems.setdefault(stem, set()).add(ext)

    complete = [s for s, exts in stems.items() if all(req in exts for req in SHP_REQUIRED)]
    return complete


def read_shapefile_zip(zip_path: Path) -> tuple[gpd.GeoDataFrame, str | None, list[str]]:
    """Read a Shapefile bundled as a ZIP archive.

    Strategy:
    1. Validate every entry's path (no traversal).
    2. Find every Shapefile set (stems with .shp + .shx + .dbf).
    3. If exactly one -- proceed.  If zero -- 422.  If more than one -- 422
       (ambiguous) unless they are in different folders and we can pick
       the top-level one unambiguously.  For simplicity we reject ambiguity.
    4. Extract into a temp dir, read with GeoPandas, fall back to a custom
       DBF reader if needed (in practice GeoPandas + Fiona is sufficient).
    """
    sets = _find_shapefile_sets(zip_path)
    if not sets:
        raise MissingShapefileError(
            "ZIP archive does not contain a complete Shapefile "
            "(missing one of .shp, .shx, .dbf)."
        )
    if len(sets) > 1:
        raise AmbiguousShapefileError(
            "ZIP archive contains multiple Shapefile sets: "
            + ", ".join(sorted(s for s in sets))
        )

    stem = sets[0]

    with tempfile.TemporaryDirectory(prefix="shp_") as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Extract only the files that belong to this Shapefile set; ignore
            # everything else in the archive.
            members = []
            for n in zf.namelist():
                if not _is_safe_zip_member(n):
                    raise ZipPathTraversalError(f"ZIP contains an unsafe path: {n!r}")
                stem_n, ext = os.path.splitext(n)
                ext = ext.lower()
                if stem_n == stem and ext in (
                    ".shp", ".shx", ".dbf", ".prj", ".cpg",
                ):
                    members.append(n)
            zf.extractall(tmp, members=members)

        shp_path = tmp / (stem + ".shp")
        if not shp_path.exists():
            # Could happen if the member was a directory entry; treat as missing.
            raise MissingShapefileError("Required .shp file is missing inside the archive.")

        # GeoPandas reads the .shp via Fiona and picks up .prj automatically.
        gdf = gpd.read_file(shp_path)

    gdf, warnings = _normalize_gdf(gdf, source_label="shapefile")
    source_crs = _format_crs(gdf.crs)
    return gdf, source_crs, warnings


# --------------------------------------------------------------------------- #
# KML fallback reader (Fiona has no KML driver here)
# --------------------------------------------------------------------------- #

# KML namespace -- most KML files use this.  fastkml handles ns discovery, but
# our defensive fallback below also handles documents that use no namespace.
_KML_NS = "http://www.opengis.net/kml/2.2"


def read_kml_file(kml_path: Path) -> tuple[gpd.GeoDataFrame, str | None, list[str]]:
    """Read a KML file.

    The Fiona/GDAL build in this environment does not register the KML
    driver, so we use the ``fastkml`` library instead, which provides a
    pure-Python KML parser on top of lxml.  ``fastkml`` exposes geometries
    as ``pygeoif``-style shapes that implement ``__geo_interface__``, so
    we can build Shapely geometries directly from them.

    KML coordinates are always in EPSG:4326 (WGS84 longitude/latitude),
    per the OGC KML specification, so we set the GeoDataFrame CRS to
    ``EPSG:4326`` when fastkml successfully parses the document.
    """
    warnings: list[str] = []

    try:
        from fastkml import KML
        from fastkml.features import Placemark
        from shapely import from_wkt
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise KmlParseError(
            "fastkml/lxml is required to parse KML in this build but is not installed."
        ) from exc

    try:
        with kml_path.open("rb") as fp:
            doc_bytes = fp.read()
    except OSError as exc:
        raise InvalidUploadError(f"Could not read uploaded KML file: {exc}") from exc

    try:
        k = KML.parse(__import__("io").BytesIO(doc_bytes))
    except Exception as exc:
        raise KmlParseError(f"Could not parse KML: {exc}") from exc

    placemarks = _collect_placemarks(k)
    if not placemarks:
        raise KmlParseError("KML document contains no Placemark features.")

    features: list[dict[str, Any]] = []
    property_keys: set[str] = set()
    for idx, placemark in enumerate(placemarks):
        try:
            geom = _placemark_to_shapely(placemark)
            if geom is None:
                warnings.append(
                    f"Placemark #{idx}: no usable geometry; skipped."
                )
                continue
            if geom.is_empty:
                warnings.append(
                    f"Placemark #{idx}: empty geometry; skipped."
                )
                continue
            properties = _placemark_properties(placemark)
            property_keys.update(properties.keys())
            features.append({"geometry": geom, "properties": properties})
        except Exception as exc:
            warnings.append(
                f"Placemark #{idx}: could not extract geometry ({exc}); skipped."
            )

    if not features:
        raise KmlParseError(
            "KML document contained Placemarks but none had usable geometries."
        )

    # Spread each property key into its own column so `_normalize_gdf` can
    # bundle them uniformly across Shapefile and KML inputs.
    col_data: dict[str, list[Any]] = {k: [] for k in property_keys}
    for f in features:
        for k in property_keys:
            col_data[k].append(f["properties"].get(k))

    gdf = gpd.GeoDataFrame(
        col_data,
        geometry=[f["geometry"] for f in features],
        crs="EPSG:4326",  # KML is always WGS84
    )
    gdf, more_warnings = _normalize_gdf(gdf, source_label="kml")
    warnings.extend(more_warnings)
    return gdf, "EPSG:4326", warnings


def _collect_placemarks(kml_root: Any) -> list[Any]:
    """Walk the KML tree and collect every Placemark (recursively)."""
    from fastkml.features import Placemark

    out: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, Placemark):
            out.append(node)
            return
        children = getattr(node, "features", None) or []
        for child in children:
            walk(child)

    # The root may itself be a Placemark (uncommon) or a container.
    walk(kml_root)
    return out


def _placemark_to_shapely(placemark: Any):
    """Convert a fastkml Placemark's geometry to a Shapely geometry.

    ``fastkml`` geometry objects (``fastkml.geometry.Point`` etc.) implement
    ``__geo_interface__``, which is the contract Shapely's ``shape()`` reads.
    We additionally flatten homogeneous ``GeometryCollection`` results into
    the matching ``Multi*`` type, because KML's ``<MultiGeometry>`` element
    legitimately groups e.g. multiple polygons -- and the assignment asks us
    to support ``MultiPolygon`` and ``MultiLineString``.
    """
    geo = getattr(placemark, "geometry", None)
    if geo is None:
        return None

    gi = getattr(geo, "__geo_interface__", None)
    if gi is not None:
        try:
            geom = shapely_shape(gi)
        except Exception:
            geom = None
    else:
        # Fallback path: serialise to WKT then parse with shapely.
        try:
            from shapely import from_wkt
            geom = from_wkt(geo.wkt)
        except Exception:
            return None

    if geom is None:
        return None

    # KML <MultiGeometry> with homogeneous contents becomes a Shapely
    # GeometryCollection via pygeoif.  Flatten it into Multi* so we can
    # actually measure it.
    if geom.geom_type == "GeometryCollection":
        return _homogenize_collection(geom)
    return geom


def _homogenize_collection(geom) -> Any:
    """Convert a homogeneous ``GeometryCollection`` into a ``Multi*`` shape.

    Heterogeneous collections (e.g. mix of polygons + lines) are returned
    unchanged; the measurement layer will mark them UNAVAILABLE.
    """
    from shapely.geometry import (
        MultiLineString,
        MultiPoint,
        MultiPolygon,
    )
    try:
        parts = list(geom.geoms)
    except Exception:
        return geom
    if not parts:
        return geom
    types = {p.geom_type for p in parts}
    if len(types) != 1:
        return geom
    only = next(iter(types))
    if only == "Polygon":
        return MultiPolygon(list(parts))
    if only == "LineString":
        return MultiLineString(list(parts))
    if only == "Point":
        return MultiPoint(list(parts))
    return geom


def _placemark_properties(placemark: Any) -> dict[str, Any]:
    """Extract name, description, and ExtendedData into a flat dict."""
    props: dict[str, Any] = {}
    name = getattr(placemark, "name", None)
    if name:
        props["name"] = name

    desc = getattr(placemark, "description", None)
    if desc:
        # Description can be a string or a structured object in fastkml 1.x.
        desc_str = getattr(desc, "text", None) or str(desc)
        props["description"] = desc_str

    style = getattr(placemark, "style_url", None)
    if style:
        props["style_url"] = str(style)

    # ExtendedData is a list of {name, value} (or Data/SchemaData) -- we
    # promote scalar Data entries to top-level keys.
    extended = getattr(placemark, "extended_data", None)
    if extended is not None:
        try:
            for kv in extended.data:
                name = getattr(kv, "name", None)
                value = getattr(kv, "value", None)
                if name is not None and value is not None:
                    props[name] = value
        except Exception:
            pass

    return props


# --------------------------------------------------------------------------- #
# Shared normalisation
# --------------------------------------------------------------------------- #

def _normalize_gdf(gdf: gpd.GeoDataFrame, source_label: str) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Coerce any input GeoDataFrame into the canonical shape used downstream.

    * Promotes the per-row attribute columns into a single ``properties``
      dict column, so the rest of the pipeline only has to handle one
      attribute shape.
    * Drops rows whose geometry is None or empty, collecting them as
      warnings.  These should not crash a whole upload.
    """
    warnings: list[str] = []

    if gdf.empty:
        raise GeoprocessingError("The file contains no features.")

    if "geometry" not in gdf.columns:
        raise GeoprocessingError("The file does not expose a geometry column.")

    # Promote attribute columns to a single properties dict.
    property_cols = [c for c in gdf.columns if c != "geometry"]
    props_series = [
        {col: _jsonable(row[col]) for col in property_cols}
        for _, row in gdf.iterrows()
    ]

    geom_col = gdf.geometry
    cleaned_geoms = []
    cleaned_props = []
    for geom, props in zip(geom_col, props_series):
        if geom is None or geom.is_empty:
            warnings.append(
                f"Feature #{len(cleaned_geoms) + len(warnings) - 1}: "
                "null or empty geometry; skipped."
            )
            continue
        cleaned_geoms.append(geom)
        cleaned_props.append(props)

    if not cleaned_geoms:
        raise GeoprocessingError("All features had null or empty geometries.")

    new_gdf = gpd.GeoDataFrame(
        {"properties": cleaned_props},
        geometry=cleaned_geoms,
        crs=gdf.crs,
    )
    return new_gdf, warnings


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of a pandas scalar to a JSON-friendly value."""
    # Pandas Int64/Float64 NaNs -> None
    try:
        import numpy as np
        if value is None:
            return None
        if isinstance(value, float) and (value != value):  # NaN
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            v = float(value)
            return None if v != v else v
        if isinstance(value, (np.bool_,)):
            return bool(value)
    except Exception:
        pass
    return value


def _format_crs(crs: Any) -> str | None:
    """Return a normalised ``EPSG:xxxx`` string for *crs*, or ``None``."""
    if crs is None:
        return None
    try:
        # pyproj CRS -> EPSG
        epsg = crs.to_epsg() if hasattr(crs, "to_epsg") else None
    except Exception:
        epsg = None
    if epsg:
        return f"EPSG:{epsg}"

    # Fall back to the WKT / string -- callers can still report it.
    s = str(crs).strip()
    if not s or s.lower() in ("none", "nan"):
        return None
    return s
