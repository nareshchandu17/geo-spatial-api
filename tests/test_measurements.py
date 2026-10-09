"""File info and measurement endpoints."""

from __future__ import annotations

import math

from tests.helpers import upload_file


# --------------------------------------------------------------------------- #
# 3. Polygon area calculation
# --------------------------------------------------------------------------- #

def test_polygon_area_calculation(client, polygon_zip):
    path, _ = polygon_zip
    r = upload_file(client, path, "survey.zip")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    assert m.status_code == 200
    feat = m.json()["features"][0]
    assert feat["geometry_type"] == "Polygon"
    assert feat["measurement_status"] == "COMPLETED"
    assert "area_m2" in feat["measurements"]
    assert "area_km2" in feat["measurements"]
    a = feat["measurements"]["area_m2"]
    assert math.isfinite(a)
    # The fixture polygon spans ~0.01deg lon x ~0.009deg lat near
    # lon=78, lat=29; in UTM that's ~970_000 m^2 (about 1 km^2).
    assert 500_000 < a < 2_000_000, f"area {a} outside expected range"
    # area_km2 should equal area_m2 / 1_000_000.
    assert abs(feat["measurements"]["area_km2"] * 1_000_000 - a) < 1e-3


def test_projected_metric_area_calculation(client, projected_zip):
    """A 1000 m x 1000 m square in UTM 43N must have area == 1,000,000 m^2."""
    path, _ = projected_zip
    r = upload_file(client, path, "utm.zip")
    file_id = r.json()["id"]
    assert r.json()["source_crs"] == "EPSG:32643"
    assert r.json()["measurement_crs"] == "EPSG:32643"  # already metric
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    a = feat["measurements"]["area_m2"]
    assert math.isfinite(a)
    assert abs(a - 1_000_000.0) < 1e-3, f"expected 1e6, got {a}"


# --------------------------------------------------------------------------- #
# 4. LineString length calculation
# --------------------------------------------------------------------------- #

def test_linestring_length_calculation(client, line_zip):
    path, _ = line_zip
    r = upload_file(client, path, "line.zip")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    assert feat["geometry_type"] == "LineString"
    assert feat["measurement_status"] == "COMPLETED"
    assert "length_m" in feat["measurements"]
    assert "length_km" in feat["measurements"]
    length = feat["measurements"]["length_m"]
    assert math.isfinite(length)
    assert length > 0
    assert abs(feat["measurements"]["length_km"] * 1000 - length) < 1e-3


def test_linestring_length_via_kml(client, line_kml):
    path, _ = line_kml
    r = upload_file(client, path, "line.kml")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    assert feat["geometry_type"] == "LineString"
    assert feat["measurement_status"] == "COMPLETED"
    assert feat["measurements"]["length_m"] > 0


# --------------------------------------------------------------------------- #
# 5. Point handling
# --------------------------------------------------------------------------- #

def test_point_handling(client, point_zip):
    path, _ = point_zip
    r = upload_file(client, path, "pt.zip")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    assert feat["geometry_type"] == "Point"
    assert feat["measurement_status"] == "NOT_REQUIRED"
    assert feat["measurements"] == {}


def test_point_handling_via_kml(client, point_kml):
    path, _ = point_kml
    r = upload_file(client, path, "pt.kml")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    assert feat["geometry_type"] == "Point"
    assert feat["measurement_status"] == "NOT_REQUIRED"
    assert feat["measurements"] == {}


# --------------------------------------------------------------------------- #
# 6. Geographic CRS transformation EPSG:4326 -> projected
# 7. Correct reporting of source CRS and measurement CRS
# --------------------------------------------------------------------------- #

def test_geographic_crs_to_projected(client, polygon_zip):
    path, _ = polygon_zip
    r = upload_file(client, path, "survey.zip")
    body = r.json()
    assert body["source_crs"] == "EPSG:4326"
    # Measurement CRS must NOT be EPSG:4326 -- it must be a projected UTM.
    assert body["measurement_crs"] != "EPSG:4326"
    assert body["measurement_crs"].startswith("EPSG:326")  # northern hemisphere UTM
    assert body["measurement_crs"] != body["source_crs"]


def test_source_and_measurement_crs_persisted(client, projected_zip):
    path, _ = projected_zip
    r = upload_file(client, path, "utm.zip")
    file_id = r.json()["id"]
    info = client.get(f"/api/files/{file_id}/").json()
    meas = client.get(f"/api/files/{file_id}/measurements/").json()
    assert info["source_crs"] == "EPSG:32643"
    assert info["measurement_crs"] == "EPSG:32643"
    assert meas["source_crs"] == "EPSG:32643"
    assert meas["measurement_crs"] == "EPSG:32643"


# --------------------------------------------------------------------------- #
# 8. Geographic measurements are NOT calculated in degrees
# --------------------------------------------------------------------------- #

def test_measurements_not_in_degrees(client, polygon_zip):
    """The area reported for a geographic-CRS polygon must be in m^2, NOT in
    degree^2 (which would be ~9e-5 for our fixture)."""
    path, _ = polygon_zip
    r = upload_file(client, path, "survey.zip")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    area = feat["measurements"]["area_m2"]
    # Sanity: area in m^2 for a ~0.01deg x 0.009deg polygon at lat=29
    # should be ~970_000 m^2 (about 1 km^2).  A degree^2 value would be
    # ~9e-5 (basically zero).  Anything < 1 means we measured in degrees.
    assert area > 1, f"Area {area} looks like degree^2, not m^2"
    assert area > 10_000  # At least a hectare -- clearly not degree units.


def test_no_nan_or_infinity_in_measurements(client, polygon_zip):
    path, _ = polygon_zip
    r = upload_file(client, path, "survey.zip")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    for k, v in feat["measurements"].items():
        assert isinstance(v, (int, float))
        assert math.isfinite(v), f"{k}={v} is not finite"


# --------------------------------------------------------------------------- #
# 14. Unknown file IDs -> 404
# --------------------------------------------------------------------------- #

def test_unknown_file_id_info_404(client):
    r = client.get("/api/files/nonexistent-id/")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_unknown_file_id_measurements_404(client):
    r = client.get("/api/files/nonexistent-id/measurements/")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 15. Persistence of results across independent API requests
# --------------------------------------------------------------------------- #

def test_persistence_across_requests(client, polygon_kml):
    """Upload is one request; info + measurements are two more requests.
    All must see the same persisted data, and the data must survive a
    fresh TestClient session restart."""
    path, _ = polygon_kml
    r = upload_file(client, path, "survey.kml")
    file_id = r.json()["id"]
    original = r.json()

    # 1) Info request
    info = client.get(f"/api/files/{file_id}/").json()
    assert info["id"] == original["id"]
    assert info["filename"] == original["filename"]
    assert info["feature_count"] == original["feature_count"]
    assert info["source_crs"] == original["source_crs"]
    assert info["measurement_crs"] == original["measurement_crs"]

    # 2) Measurements request (different request, same DB)
    m = client.get(f"/api/files/{file_id}/measurements/").json()
    assert m["file_id"] == file_id
    assert m["feature_count"] == original["feature_count"]
    assert m["features"][0]["measurement_status"] == "COMPLETED"
    assert m["features"][0]["measurements"]["area_m2"] > 0

    # 3) Restart the test client (re-instantiate the app) -- the DB must
    #    survive because it's on disk, not in memory.
    from fastapi.testclient import TestClient
    import main as main_mod
    with TestClient(main_mod.app) as new_client:
        info2 = new_client.get(f"/api/files/{file_id}/").json()
        assert info2["id"] == file_id
        assert info2["source_crs"] == original["source_crs"]
        m2 = new_client.get(f"/api/files/{file_id}/measurements/").json()
        assert m2["features"][0]["measurements"] == m["features"][0]["measurements"]


# --------------------------------------------------------------------------- #
# Mixed-geometry KML (Polygon + LineString + Point) -- Shapefile can't hold
# mixed types so we use KML here.
# --------------------------------------------------------------------------- #

def test_mixed_geometry_kml(client, mixed_kml):
    path, _ = mixed_kml
    r = upload_file(client, path, "mixed.kml")
    assert r.status_code == 201, r.text
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/").json()
    assert m["feature_count"] == 3
    statuses = [f["measurement_status"] for f in m["features"]]
    types = [f["geometry_type"] for f in m["features"]]
    assert "Polygon" in types
    assert "LineString" in types
    assert "Point" in types
    # Polygon -> COMPLETED with area_m2; Line -> COMPLETED with length_m; Point -> NOT_REQUIRED
    poly = next(f for f in m["features"] if f["geometry_type"] == "Polygon")
    line = next(f for f in m["features"] if f["geometry_type"] == "LineString")
    point = next(f for f in m["features"] if f["geometry_type"] == "Point")
    assert poly["measurement_status"] == "COMPLETED"
    assert "area_m2" in poly["measurements"]
    assert line["measurement_status"] == "COMPLETED"
    assert "length_m" in line["measurements"]
    assert point["measurement_status"] == "NOT_REQUIRED"
    assert point["measurements"] == {}


# --------------------------------------------------------------------------- #
# Source geometry is NOT mutated by measurement
# --------------------------------------------------------------------------- #

def test_source_geometry_not_mutated(client, polygon_zip):
    """The geometry returned in the API response must be in the SOURCE CRS
    (EPSG:4326 here), not in the measurement CRS (UTM)."""
    path, _ = polygon_zip
    r = upload_file(client, path, "survey.zip")
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/")
    feat = m.json()["features"][0]
    geom = feat["geometry"]
    assert geom["type"] == "Polygon"
    coords = geom["coordinates"][0]
    # Source coordinates are lon/lat around (78, 29).  Reprojected UTM
    # coordinates would be like (200000, 3200000).
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    assert 77 < min(xs) < max(xs) < 80, "x looks like UTM, not lon"
    assert 28 < min(ys) < max(ys) < 30, "y looks like UTM, not lat"
    assert feat["crs"] == "EPSG:4326"  # source CRS preserved
