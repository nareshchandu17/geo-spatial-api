"""Health check endpoint and HTML preview page."""

from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "service" in body
    assert body["database"] == "ok"


def test_openapi_docs_available(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Geospatial File Measurement API"
    paths = set(schema["paths"].keys())
    assert "/health" in paths
    assert "/api/files/" in paths
    assert "/api/files/{file_id}/" in paths
    assert "/api/files/{file_id}/measurements/" in paths


def test_preview_page_available(client):
    """GET / must serve the HTML playground with the Leaflet + dropzone."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Geospatial File Measurement API" in body
    assert "leaflet" in body.lower()  # Leaflet CSS+JS CDN refs
    assert "Drop a .zip or .kml here" in body
    # The preview must NOT appear in the OpenAPI schema (it's a UI, not an API).
    schema = client.get("/openapi.json").json()
    assert "/" not in schema["paths"]
