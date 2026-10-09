# Geospatial File Measurement API -- container image.
#
# Multi-stage build that keeps the final image small.  The geospatial
# stack (geopandas, shapely, pyproj, fiona) ships binary wheels for the
# python:3.12-slim base -- no need to build PROJ/GDAL from source.

FROM python:3.12-slim AS base

# System packages needed by fiona / pyogrio at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-dev \
        libproj-dev \
        libgdal-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY . .

# Pre-create the data directory; the SQLite DB lives there at runtime.
RUN mkdir -p /app/data
ENV GEOSPATIAL_DATA_DIR=/app/data
ENV GEOSPATIAL_DATABASE_PATH=/app/data/geospatial.db

EXPOSE 8000

# Run the app.  Use --host 0.0.0.0 so the container is reachable from the host.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
