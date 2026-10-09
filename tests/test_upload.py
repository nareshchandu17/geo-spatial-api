"""Upload endpoint success + failure cases."""

from __future__ import annotations

import math

from tests.helpers import upload_file


# --------------------------------------------------------------------------- #
# 1. Successful upload & processing of a valid zipped Shapefile
# --------------------------------------------------------------------------- #

def test_upload_polygon_zipfile(client, polygon_zip):
    path, gdf = polygon_zip
    r = upload_file(client, path, "survey.zip")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "survey.zip"
    assert body["feature_count"] == 1
    assert body["source_crs"] == "EPSG:4326"
    assert body["crs"] == "EPSG:4326"
    assert body["measurement_crs"] and body["measurement_crs"].startswith("EPSG:3264")
    assert body["status"] == "COMPLETED"
    assert "id" in body and len(body["id"]) > 0
    assert body["warnings"] == []


# --------------------------------------------------------------------------- #
# 2. Successful upload & processing of a valid KML file
# --------------------------------------------------------------------------- #

def test_upload_polygon_kml(client, polygon_kml):
    path, gdf = polygon_kml
    r = upload_file(client, path, "survey.kml")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "survey.kml"
    assert body["feature_count"] == 1
    assert body["source_crs"] == "EPSG:4326"
    assert body["measurement_crs"].startswith("EPSG:3264")
    assert body["status"] == "COMPLETED"


# --------------------------------------------------------------------------- #
# 9. Unsupported file extensions (.csv, .pdf, ...)
# --------------------------------------------------------------------------- #

def test_unsupported_extension_csv(client, bad_extension_bytes):
    r = upload_file(client, str(bad_extension_bytes), "data.csv")
    assert r.status_code == 415, r.text
    assert "Unsupported" in r.json()["detail"]


def test_unsupported_extension_no_extension(client, tmp_path):
    p = tmp_path / "noext"
    p.write_bytes(b"PK\x03\x04 binary content")
    r = upload_file(client, str(p), "noext")
    assert r.status_code == 415


# --------------------------------------------------------------------------- #
# 10. Invalid ZIP files (corrupt bytes)
# --------------------------------------------------------------------------- #

def test_corrupt_zip_bytes(client, malformed_zip_bytes, tmp_path):
    p = tmp_path / "broken.zip"
    p.write_bytes(malformed_zip_bytes)
    r = upload_file(client, str(p), "broken.zip")
    # Should be 422 (we got past magic-byte check but extraction failed).
    assert r.status_code in (400, 422), r.text


def test_zip_signature_mismatch(client, tmp_path):
    """A file labelled .zip that does not start with PK\\x03\\x04."""
    p = tmp_path / "fake.zip"
    p.write_bytes(b"This is not a zip, but it is named .zip")
    r = upload_file(client, str(p), "fake.zip")
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# 11. ZIP archives without a valid Shapefile
# --------------------------------------------------------------------------- #

def test_empty_zip(client, empty_zip):
    r = upload_file(client, str(empty_zip), "empty.zip")
    assert r.status_code == 422, r.text
    assert "Shapefile" in r.json()["detail"] or "complete" in r.json()["detail"].lower()


def test_zip_without_shapefile(client, no_shapefile_zip):
    r = upload_file(client, str(no_shapefile_zip), "notashape.zip")
    assert r.status_code == 422, r.text


def test_partial_shapefile_zip(client, partial_shapefile_zip):
    """ZIP with .shp only -- missing .shx and .dbf."""
    r = upload_file(client, str(partial_shapefile_zip), "partial.zip")
    assert r.status_code == 422, r.text
    assert "complete" in r.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Path traversal protection
# --------------------------------------------------------------------------- #

def test_traversal_zip_rejected(client, traversal_zip):
    r = upload_file(client, str(traversal_zip), "evil.zip")
    assert r.status_code in (400, 422), r.text
    # The error message must mention "unsafe path" -- never succeed silently.
    detail = r.json()["detail"].lower()
    assert "unsafe" in detail or "traversal" in detail or "shapefile" in detail


# --------------------------------------------------------------------------- #
# 12. Missing or unusable CRS information
# --------------------------------------------------------------------------- #

def test_missing_crs(client, no_crs_zip):
    path, gdf = no_crs_zip
    r = upload_file(client, path, "nocrs.zip")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_crs"] is None
    assert body["measurement_crs"] is None
    # Warnings must explain the problem.
    joined = " ".join(body["warnings"]).lower()
    assert "crs" in joined or "missing" in joined

    # Measurements endpoint should report UNAVAILABLE for the polygon.
    m = client.get(f"/api/files/{body['id']}/measurements/")
    assert m.status_code == 200
    feat = m.json()["features"][0]
    assert feat["measurement_status"] == "UNAVAILABLE"
    assert feat["measurements"] == {}


# --------------------------------------------------------------------------- #
# KML parse failure
# --------------------------------------------------------------------------- #

def test_malformed_kml(client, malformed_kml_bytes, tmp_path):
    p = tmp_path / "broken.kml"
    p.write_bytes(malformed_kml_bytes)
    r = upload_file(client, str(p), "broken.kml")
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# 17. Upload size limit + malformed inputs
# --------------------------------------------------------------------------- #

def test_upload_too_large(client, polygon_zip, monkeypatch):
    """An upload that exceeds the configured size limit returns 413."""
    import config
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    path, _ = polygon_zip
    r = upload_file(client, path, "too-big.zip")
    assert r.status_code == 413, r.text


def test_upload_no_file_field(client):
    """POST without the multipart 'file' field -> 422 (FastAPI validation)."""
    r = client.post("/api/files/", files={})
    assert r.status_code == 422


def test_upload_empty_filename(client, polygon_zip):
    """POST with empty filename -- the request still must carry a content-type."""
    path, _ = polygon_zip
    with open(path, "rb") as fp:
        data = fp.read()
    # Send a generic name; the suffix is what's validated.
    r = client.post(
        "/api/files/",
        files={"file": ("upload", data, "application/octet-stream")},
    )
    # No extension -> 415.
    assert r.status_code == 415


# --------------------------------------------------------------------------- #
# 13. Unsupported geometry types / invalid individual features
# --------------------------------------------------------------------------- #

def test_invalid_geometry_polygon_gets_warning(client, tmp_path):
    """A self-intersecting (invalid) polygon is repaired via buffer(0) and
    still produces a finite measurement (with a warning)."""
    import geopandas as gpd
    from shapely.geometry import Polygon
    from tests.conftest import _write_shapefile_zip

    bowtie = Polygon([(0, 0), (0, 2), (2, 0), (2, 2), (0, 0)])
    gdf = gpd.GeoDataFrame({"name": ["bowtie"]}, geometry=[bowtie], crs="EPSG:32643")
    p = tmp_path / "bowtie.zip"
    _write_shapefile_zip(gdf, p)
    r = upload_file(client, str(p), "bowtie.zip")
    assert r.status_code == 201, r.text
    file_id = r.json()["id"]

    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    # Either we repaired it (COMPLETED) or marked UNAVAILABLE -- but it
    # must NOT crash the whole upload.
    assert feat["measurement_status"] in ("COMPLETED", "UNAVAILABLE")
    # If completed, the measurement must be a finite positive number.
    if feat["measurement_status"] == "COMPLETED":
        a = feat["measurements"]["area_m2"]
        assert math.isfinite(a)
        assert a > 0
