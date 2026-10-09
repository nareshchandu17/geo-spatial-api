"""Application configuration.

Settings are loaded from environment variables with sensible defaults so
the project can be run without any extra configuration. Override via a
``.env`` file or shell environment variables when needed.
"""

from __future__ import annotations

import os
from pathlib import Path

# Base directory of the application (the folder that contains main.py).
BASE_DIR: Path = Path(__file__).resolve().parent

# Where the SQLite database and any runtime artefacts live.
DATA_DIR: Path = Path(os.getenv("GEOSPATIAL_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite database file path.
DATABASE_PATH: Path = Path(
    os.getenv("GEOSPATIAL_DATABASE_PATH", DATA_DIR / "geospatial.db")
)

# Maximum upload size in bytes. Default = 50 MiB.
MAX_UPLOAD_BYTES: int = int(os.getenv("GEOSPATIAL_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

# Allowed upload extensions (lower-case, with leading dot).
ALLOWED_EXTENSIONS: tuple[str, ...] = (".zip", ".kml")

# Magic-byte signatures we accept.  We never trust the filename / Content-Type
# alone; we additionally inspect the first few bytes of every upload.
# Each value is a tuple of allowed start-byte signatures.
ACCEPTED_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    # PK\x03\x04 -- local file header (normal non-empty zip)
    # PK\x05\x06 -- end-of-central-directory (empty zip)
    # PK\x07\x08 -- ZIP64 EOCD locator
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    # KML is XML; it can start with either <?xml or <kml (when the prolog
    # is omitted).  We accept either, plus an optional leading UTF-8 BOM.
    ".kml": (b"<?xml", b"<kml", b"\xef\xbb\xbf<?xml", b"\xef\xbb\xbf<kml"),
}

# EPSG codes that we treat as safe "fallback" geographic CRS when the source
# of the data really cannot be determined.  This is intentionally an empty
# tuple -- the application must NOT silently assume a CRS for ambiguous data.
GEOGRAPHIC_FALLBACK_CRS: tuple[int, ...] = ()

# Whether to verify the measurement CRS unit is "metre" before labelling
# measurements as m / m^2.  Always True in production.
VERIFY_METRIC_UNIT: bool = True
