"""Pydantic response models.

Used by FastAPI for OpenAPI documentation.  The actual API responses
always carry a superset of these fields, so ``response_model_exclude_none``
is enabled at the route level where appropriate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FileInfoResponse(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str | None = None
    source_crs: str | None = None
    measurement_crs: str | None = None
    status: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class FeatureMeasurement(BaseModel):
    feature_index: int
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    properties: dict[str, Any]
    measurements: dict[str, Any]
    measurement_status: str
    warnings: list[str]


class MeasurementsResponse(BaseModel):
    file_id: str
    filename: str
    feature_count: int
    source_crs: str | None
    measurement_crs: str | None
    features: list[FeatureMeasurement]


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "geospatial-file-measurement-api"
    database: str = "ok"


class ErrorResponse(BaseModel):
    detail: str
