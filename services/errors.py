"""Custom exception hierarchy used across the application.

These are translated into HTTP responses by FastAPI exception handlers
registered in :mod:`main`.  Keeping them in one place avoids circular
imports between the API and the service layer.
"""

from __future__ import annotations


class GeoAPIError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 400
    detail: str = "Bad request"

    def __init__(self, detail: str | None = None, status_code: int | None = None):
        self.detail = detail or self.detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


class UnsupportedFileTypeError(GeoAPIError):
    """Extension / content-type is not accepted (e.g. .csv, .pdf)."""

    status_code = 415
    detail = "Unsupported file type. Only .zip (containing a Shapefile) and .kml are accepted."


class FileTooLargeError(GeoAPIError):
    """Upload exceeded the configured size limit."""

    status_code = 413
    detail = "Upload exceeds the maximum allowed size."


class InvalidUploadError(GeoAPIError):
    """File looks valid by name but its bytes are not (e.g. not a real zip)."""

    status_code = 400
    detail = "The uploaded file is not valid."


class MissingShapefileError(GeoAPIError):
    """ZIP archive does not contain a usable Shapefile set."""

    status_code = 422
    detail = "ZIP archive does not contain a complete, usable Shapefile (.shp + .shx + .dbf)."


class AmbiguousShapefileError(GeoAPIError):
    """ZIP archive contains multiple candidate Shapefile sets."""

    status_code = 422
    detail = "ZIP archive contains multiple Shapefile sets; please upload a single Shapefile."


class KmlParseError(GeoAPIError):
    """KML could not be parsed."""

    status_code = 422
    detail = "The uploaded file is not a valid KML document."


class GeoprocessingError(GeoAPIError):
    """The file was readable but could not be turned into features."""

    status_code = 422
    detail = "The uploaded file could not be processed as geospatial data."


class FileNotFoundError_(GeoAPIError):
    """File id does not exist in the database."""

    status_code = 404
    detail = "File not found."


class MissingCrsError(GeoAPIError):
    """Soft signal: data is usable but CRS is missing.  Handled inline, not raised directly to the API in most cases."""


class ZipPathTraversalError(GeoAPIError):
    """ZIP contains an entry with ../ or absolute path."""

    status_code = 400
    detail = "ZIP archive contains an unsafe path."
