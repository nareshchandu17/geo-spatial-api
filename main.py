"""Application entry point.

Run locally with::

    uvicorn main:app --reload

OpenAPI documentation is available at http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import database as db
from api.routes import router
from services.errors import GeoAPIError

# Configure logging -- a single, predictable format.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("geospatial_api")


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="Geospatial File Measurement API",
        description=(
            "Upload a zipped Shapefile or a KML file.  The API extracts "
            "features, detects the source CRS, selects a suitable projected "
            "CRS for metric measurements, computes polygon areas and "
            "LineString lengths, and persists the results in SQLite."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Initialise the schema at import time so a fresh checkout just works.
    try:
        db.init_db()
    except Exception as exc:  # pragma: no cover
        logger.error("Database initialisation failed: %s", exc)

    app.include_router(router)

    # --------------------------------------------------------------------- #
    # Exception handlers
    # --------------------------------------------------------------------- #

    @app.exception_handler(GeoAPIError)
    async def geo_api_error_handler(request: Request, exc: GeoAPIError):
        # Never leak the raw traceback; the message is the contract.
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Log the full error server-side, but return a generic 500 to the
        # client -- we never want to leak stack traces, file paths, etc.
        logger.exception("Unhandled error processing %s: %s", request.url, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
