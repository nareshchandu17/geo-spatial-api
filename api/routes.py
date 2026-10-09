"""API route handlers.

The routes are intentionally thin -- all real work lives in the service
layer.  Routes only translate HTTP into service calls and translate service
errors into HTTP responses.
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse

import database as db
import config
from api.preview import PREVIEW_HTML
from services.errors import (
    GeoAPIError,
    FileNotFoundError_,
)
from services.processor import get_measurements_response, process_upload
from schemas import (
    ErrorResponse,
    FileInfoResponse,
    HealthResponse,
    MeasurementsResponse,
)

router = APIRouter()


# --------------------------------------------------------------------------- #
# Interactive HTML preview
# --------------------------------------------------------------------------- #

@router.get("/", include_in_schema=False, tags=["preview"])
def preview() -> HTMLResponse:
    """Self-contained HTML playground: upload a file, see the JSON
    response, and visualise every feature's geometry on a Leaflet map.
    """
    return HTMLResponse(PREVIEW_HTML)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #

@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness check.  Returns ``200 {"status": "ok"}`` when the process
    is up and the database file is reachable."""
    db_ok = "ok"
    try:
        db.init_db()
    except Exception as exc:  # pragma: no cover
        db_ok = f"error: {exc}"
    return HealthResponse(status="ok", database=db_ok)


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #

@router.post(
    "/api/files/",
    response_model=FileInfoResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["files"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid upload."},
        413: {"model": ErrorResponse, "description": "Upload too large."},
        415: {"model": ErrorResponse, "description": "Unsupported file type."},
        422: {"model": ErrorResponse, "description": "File could not be processed."},
        500: {"model": ErrorResponse, "description": "Unexpected error."},
    },
)
def upload_file(file: UploadFile = File(..., description="A .zip (Shapefile) or .kml upload")):
    """Process a Shapefile (.zip) or KML upload.

    Multipart form field name must be ``file``.
    """
    # Read the whole upload.  We cap the read to one extra byte so we can
    # detect an over-limit upload cleanly (413) rather than letting the
    # service crash with OOM.  ``MAX_UPLOAD_BYTES`` is read at call time so
    # tests can monkeypatch the limit.
    max_bytes = config.MAX_UPLOAD_BYTES
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        from services.errors import FileTooLargeError
        raise FileTooLargeError(
            f"Upload exceeds the configured limit of {max_bytes} bytes."
        )

    filename = file.filename or "upload"
    record = process_upload(filename=filename, content=content)
    return record


# --------------------------------------------------------------------------- #
# File info
# --------------------------------------------------------------------------- #

@router.get(
    "/api/files/{file_id}/",
    response_model=FileInfoResponse,
    tags=["files"],
    responses={
        404: {"model": ErrorResponse, "description": "File not found."},
    },
)
def get_file_info(file_id: str):
    record = db.get_file_record(file_id)
    if record is None:
        raise FileNotFoundError_()
    return record


# --------------------------------------------------------------------------- #
# Measurements
# --------------------------------------------------------------------------- #

@router.get(
    "/api/files/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    tags=["files"],
    responses={
        404: {"model": ErrorResponse, "description": "File not found."},
    },
)
def get_measurements(file_id: str):
    payload = get_measurements_response(file_id)
    if payload is None:
        raise FileNotFoundError_()
    return payload
