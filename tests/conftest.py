"""Shared pytest fixtures.

The fixtures here build small but real geospatial files programmatically so
the test suite is fully self-contained.  Nothing is fetched from the
network, and no large sample datasets are committed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

# --------------------------------------------------------------------------- #
# Test database isolation
# --------------------------------------------------------------------------- #
#
# Tests must NOT write to the developer's ./data/geospatial.db.  We redirect
# the database file to a per-test temp path before importing the app, by
# monkeypatching the config module.  Each test session starts with a clean
# database so tests are order-independent.


@pytest.fixture(scope="session")
def temp_db_dir(tmp_path_factory):
    """Per-session temp directory containing the test SQLite DB."""
    d = tmp_path_factory.mktemp("geoapi_db")
    return d


@pytest.fixture(scope="session", autouse=True)
def _isolate_database(temp_db_dir):
    """Point the app at an isolated SQLite file before any test runs."""
    db_path = temp_db_dir / "test.db"

    # Monkeypatch the *values* used by the app at call-time.
    import config as cfg
    cfg.DATABASE_PATH = db_path
    cfg.DATA_DIR = temp_db_dir
    (temp_db_dir / "uploads").mkdir(exist_ok=True)

    # The database module imports DATABASE_PATH at module import time, so we
    # have to update it there as well.  All functions read the live attribute
    # at call time, so updating the module attribute is sufficient.
    import database as db_mod
    db_mod.DATABASE_PATH = db_path

    db_mod.init_db()
    yield
    # session teardown -- nothing to do; tmp_path is cleaned by pytest.


@pytest.fixture()
def fresh_db(_isolate_database):
    """Per-test: wipe rows so tests don't see each other's data."""
    import database as db_mod
    with db_mod.get_connection() as conn:
        conn.execute("DELETE FROM features")
        conn.execute("DELETE FROM files")
        conn.commit()
    yield


# --------------------------------------------------------------------------- #
# FastAPI TestClient
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def app(_isolate_database):
    # Re-import so the app picks up the patched config.
    import importlib
    import main as main_mod
    importlib.reload(main_mod)
    return main_mod.app


@pytest.fixture()
def client(app, fresh_db):
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Geospatial fixture builders
# --------------------------------------------------------------------------- #


def _make_survey_polygon_gdf() -> gpd.GeoDataFrame:
    """A small ~1 km^2 polygon in EPSG:4326, located in northern India."""
    # Roughly a square spanning ~0.01 degree lon x 0.009 degree lat
    # around lon=78.0, lat=29.0 (UTM zone 43N).
    poly = Polygon(
        [
            (78.00, 29.00),
            (78.01, 29.00),
            (78.01, 29.009),
            (78.00, 29.009),
            (78.00, 29.00),
        ]
    )
    return gpd.GeoDataFrame(
        {"name": ["Survey Area"], "category": ["residential"]},
        geometry=[poly],
        crs="EPSG:4326",
    )


def _make_pipeline_line_gdf() -> gpd.GeoDataFrame:
    """A LineString in EPSG:4326 (north India)."""
    line = LineString(
        [
            (78.00, 29.00),
            (78.005, 29.005),
            (78.010, 29.000),
        ]
    )
    return gpd.GeoDataFrame(
        {"name": ["Pipe A"]},
        geometry=[line],
        crs="EPSG:4326",
    )


def _make_point_gdf() -> gpd.GeoDataFrame:
    pt = Point(78.0, 29.0)
    return gpd.GeoDataFrame(
        {"name": ["Survey Marker"]},
        geometry=[pt],
        crs="EPSG:4326",
    )


def _make_mixed_gdf() -> gpd.GeoDataFrame:
    """A frame with polygon + line + point features together."""
    poly = Polygon(
        [
            (78.00, 29.00),
            (78.01, 29.00),
            (78.01, 29.01),
            (78.00, 29.01),
            (78.00, 29.00),
        ]
    )
    line = LineString([(78.00, 29.00), (78.02, 29.02)])
    pt = Point(78.005, 29.005)
    return gpd.GeoDataFrame(
        {"name": ["Survey Area", "Pipe A", "Marker"]},
        geometry=[poly, line, pt],
        crs="EPSG:4326",
    )


def _make_projected_metric_gdf() -> gpd.GeoDataFrame:
    """A 1000 m x 1000 m square in UTM 43N (EPSG:32643).  Area = 1e6 m^2."""
    poly = Polygon(
        [
            (300000, 3200000),
            (301000, 3200000),
            (301000, 3201000),
            (300000, 3201000),
            (300000, 3200000),
        ]
    )
    return gpd.GeoDataFrame(
        {"name": ["UTM Plot"]},
        geometry=[poly],
        crs="EPSG:32643",
    )


def _make_no_crs_gdf() -> gpd.GeoDataFrame:
    """A polygon with no CRS set -- used to test the missing-CRS path."""
    poly = Polygon(
        [
            (78.00, 29.00),
            (78.01, 29.00),
            (78.01, 29.01),
            (78.00, 29.01),
            (78.00, 29.00),
        ]
    )
    gdf = gpd.GeoDataFrame({"name": ["No-CRS Polygon"]}, geometry=[poly])
    return gdf.set_crs(None)


# --------------------------------------------------------------------------- #
# ZIP / Shapefile fixture builders
# --------------------------------------------------------------------------- #


def _write_shapefile_zip(gdf: gpd.GeoDataFrame, dest: Path, layer_name: str = "survey") -> Path:
    """Write *gdf* to a Shapefile set and zip it up."""
    tmpdir = tempfile.mkdtemp(prefix="shpfix_")
    try:
        # pyogrio (geopandas 1.x default) only emits the full .shp/.shx/.dbf
        # set when the destination path ends in .shp explicitly.
        base = Path(tmpdir) / f"{layer_name}.shp"
        gdf.to_file(base, driver="ESRI Shapefile")
        stem = str(base)[:-4]  # strip the .shp for stem-based lookups below

        zip_path = dest
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                p = Path(stem + ext)
                if p.exists():
                    zf.write(p, arcname=p.name)
        return zip_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_kml(gdf: gpd.GeoDataFrame, dest: Path) -> Path:
    """Write *gdf* to a KML file using a manual writer.

    We do not rely on GeoPandas' .to_file(driver='KML') because the local
    Fiona build has no KML driver.  Instead, we write a minimal, valid KML
    document directly.
    """
    kml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
    ]
    for idx, row in gdf.iterrows():
        geom = row.geometry
        name = row.get("name", f"Feature {idx}")
        kml_parts.append("<Placemark>")
        kml_parts.append(f"<name>{name}</name>")
        kml_parts.extend(_geom_to_kml(geom))
        kml_parts.append("</Placemark>")
    kml_parts.append("</Document>")
    kml_parts.append("</kml>")

    dest.write_text("\n".join(kml_parts), encoding="utf-8")
    return dest


def _geom_to_kml(geom) -> list[str]:
    """Render a Shapely geometry to a minimal KML fragment."""
    import json

    gj = geom.__geo_interface__
    gtype = gj["type"]
    coords = gj["coordinates"]

    def fmt_lonlat_xyz(c):
        # KML wants lon,lat,alt -- alt optional.
        if len(c) == 2:
            return f"{c[0]},{c[1]}"
        return f"{c[0]},{c[1]},{c[2]}"

    def fmt_coords(cs):
        return " ".join(fmt_lonlat_xyz(c) for c in cs)

    parts: list[str] = []
    if gtype == "Point":
        parts.append(f"<Point><coordinates>{fmt_lonlat_xyz(coords)}</coordinates></Point>")
    elif gtype == "LineString":
        parts.append(f"<LineString><coordinates>{fmt_coords(coords)}</coordinates></LineString>")
    elif gtype == "Polygon":
        outer = fmt_coords(coords[0])
        parts.append("<Polygon><outerBoundaryIs><LinearRing>")
        parts.append(f"<coordinates>{outer}</coordinates>")
        parts.append("</LinearRing></outerBoundaryIs></Polygon>")
    elif gtype == "MultiPolygon":
        for poly in coords:
            outer = fmt_coords(poly[0])
            parts.append("<Polygon><outerBoundaryIs><LinearRing>")
            parts.append(f"<coordinates>{outer}</coordinates>")
            parts.append("</LinearRing></outerBoundaryIs></Polygon>")
    elif gtype == "MultiLineString":
        for line in coords:
            parts.append("<LineString>")
            parts.append(f"<coordinates>{fmt_coords(line)}</coordinates>")
            parts.append("</LineString>")
    elif gtype == "MultiPoint":
        for p in coords:
            parts.append(f"<Point><coordinates>{fmt_lonlat_xyz(p)}</coordinates></Point>")
    else:
        raise ValueError(f"Unsupported geom for KML writer: {gtype}")
    return parts


# --------------------------------------------------------------------------- #
# Pytest fixtures wrapping the builders above
# --------------------------------------------------------------------------- #


@pytest.fixture()
def polygon_zip(tmp_path):
    dest = tmp_path / "polygon.zip"
    gdf = _make_survey_polygon_gdf()
    yield _write_shapefile_zip(gdf, dest), gdf


@pytest.fixture()
def line_zip(tmp_path):
    dest = tmp_path / "line.zip"
    gdf = _make_pipeline_line_gdf()
    yield _write_shapefile_zip(gdf, dest), gdf


@pytest.fixture()
def point_zip(tmp_path):
    dest = tmp_path / "point.zip"
    gdf = _make_point_gdf()
    yield _write_shapefile_zip(gdf, dest), gdf


@pytest.fixture()
def projected_zip(tmp_path):
    dest = tmp_path / "projected.zip"
    gdf = _make_projected_metric_gdf()
    yield _write_shapefile_zip(gdf, dest), gdf


@pytest.fixture()
def no_crs_zip(tmp_path):
    dest = tmp_path / "no_crs.zip"
    gdf = _make_no_crs_gdf()
    yield _write_shapefile_zip(gdf, dest), gdf


@pytest.fixture()
def polygon_kml(tmp_path):
    dest = tmp_path / "polygon.kml"
    gdf = _make_survey_polygon_gdf()
    _write_kml(gdf, dest)
    return dest, gdf


@pytest.fixture()
def line_kml(tmp_path):
    dest = tmp_path / "line.kml"
    gdf = _make_pipeline_line_gdf()
    _write_kml(gdf, dest)
    return dest, gdf


@pytest.fixture()
def point_kml(tmp_path):
    dest = tmp_path / "point.kml"
    gdf = _make_point_gdf()
    _write_kml(gdf, dest)
    return dest, gdf


@pytest.fixture()
def mixed_kml(tmp_path):
    dest = tmp_path / "mixed.kml"
    gdf = _make_mixed_gdf()
    _write_kml(gdf, dest)
    return dest, gdf


# --------------------------------------------------------------------------- #
# Low-level broken inputs
# --------------------------------------------------------------------------- #


@pytest.fixture()
def empty_zip(tmp_path):
    """A valid ZIP with no entries at all."""
    dest = tmp_path / "empty.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        pass  # no members
    return dest


@pytest.fixture()
def no_shapefile_zip(tmp_path):
    """A valid ZIP that contains only unrelated files (e.g. README.txt)."""
    dest = tmp_path / "noshape.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("README.txt", "this is not a shapefile")
        zf.writestr("data.csv", "id,name\n1,foo\n")
    return dest


@pytest.fixture()
def partial_shapefile_zip(tmp_path):
    """A ZIP that contains only .shp (no .shx/.dbf)."""
    dest = tmp_path / "partial.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("survey.shp", b"\x00\x00\x27\x0a" + b"\x00" * 96)
    return dest


@pytest.fixture()
def traversal_zip(tmp_path):
    """A ZIP containing an absolute path entry (should be rejected)."""
    dest = tmp_path / "traversal.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("/etc/passwd", "evil")
    return dest


@pytest.fixture()
def bad_extension_bytes(tmp_path):
    """Bytes for an unsupported extension (.csv)."""
    dest = tmp_path / "data.csv"
    dest.write_text("id,name\n1,foo\n")
    return dest


@pytest.fixture()
def malformed_zip_bytes(tmp_path):
    """Bytes that start with PK\\x03\\x04 but are not actually a valid ZIP."""
    # Local file header signature but truncated/corrupt.
    return b"PK\x03\x04" + b"\x00" * 30 + b"corrupt"


@pytest.fixture()
def malformed_kml_bytes(tmp_path):
    """A .kml-looking file that is not valid XML."""
    return b'<?xml version="1.0"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><broken'
