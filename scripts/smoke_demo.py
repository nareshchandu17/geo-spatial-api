#!/usr/bin/env python3
"""End-to-end smoke test -- a minimal demo of all 4 endpoints.

Run it with::

    python3 scripts/smoke_demo.py

It uploads a tiny synthetic KML polygon, prints the file-info and
measurement responses, and exits.  Useful for a quick sanity check that
the server is up and reachable; it is NOT a replacement for pytest.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx
from shapely.geometry import Polygon


def build_kml() -> bytes:
    poly = Polygon(
        [
            (78.00, 29.00),
            (78.01, 29.00),
            (78.01, 29.009),
            (78.00, 29.009),
            (78.00, 29.00),
        ]
    )
    gj = poly.__geo_interface__
    coords = " ".join(f"{c[0]},{c[1]}" for c in gj["coordinates"][0])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "<Document>\n"
        "<Placemark><name>Smoke Test Polygon</name>\n"
        "<Polygon><outerBoundaryIs><LinearRing>"
        f"<coordinates>{coords}</coordinates>"
        "</LinearRing></outerBoundaryIs></Polygon>\n"
        "</Placemark>\n"
        "</Document></kml>\n"
    ).encode("utf-8")


def main(base_url: str = "http://127.0.0.1:8000") -> int:
    print(f"Smoke-testing API at {base_url}")
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        r = client.get("/health")
        print(f"GET /health           -> {r.status_code} {r.json()}")

        kml = build_kml()
        r = client.post(
            "/api/files/",
            files={"file": ("survey.kml", kml, "application/vnd.google-earth.kml+xml")},
        )
        print(f"POST /api/files/      -> {r.status_code}")
        if r.status_code != 201:
            print(r.text)
            return 1
        body = r.json()
        file_id = body["id"]
        print(f"  id              = {body['id']}")
        print(f"  filename        = {body['filename']}")
        print(f"  feature_count   = {body['feature_count']}")
        print(f"  source_crs      = {body['source_crs']}")
        print(f"  measurement_crs = {body['measurement_crs']}")
        print(f"  status          = {body['status']}")
        print(f"  warnings        = {body['warnings']}")

        r = client.get(f"/api/files/{file_id}/")
        print(f"GET /api/files/{{id}}/ -> {r.status_code}")

        r = client.get(f"/api/files/{file_id}/measurements/")
        print(f"GET .../measurements/ -> {r.status_code}")
        feat = r.json()["features"][0]
        print(f"  geometry_type  = {feat['geometry_type']}")
        print(f"  measurements   = {feat['measurements']}")
        print(f"  status         = {feat['measurement_status']}")

    print("\nSmoke test PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
