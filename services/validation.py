"""Upload validation.

We deliberately do NOT trust the filename or the ``Content-Type`` header
alone.  Both are user-controlled and trivially spoofable.  Every upload is
checked three ways:

1. **Extension** -- the suffix must be one of :data:`config.ALLOWED_EXTENSIONS`.
2. **Magic bytes** -- the first bytes of the file must match the expected
   signature for that extension.
3. **Size** -- the upload must not exceed :data:`config.MAX_UPLOAD_BYTES`.
"""

from __future__ import annotations

import os
from pathlib import Path

import config
from services.errors import (
    FileTooLargeError,
    InvalidUploadError,
    UnsupportedFileTypeError,
)


# --------------------------------------------------------------------------- #
# Filename helpers
# --------------------------------------------------------------------------- #

def get_extension(filename: str) -> str:
    """Return the lower-cased extension of *filename* including the dot."""
    # Use os.path.splitext so filenames like ``my.data.kml`` work, but
    # ``.tar.gz`` style double-extensions are out of scope for this project.
    _, ext = os.path.splitext(filename)
    return ext.lower()


def validate_filename(filename: str) -> str:
    """Return the lower-cased extension if accepted, else raise 415."""
    ext = get_extension(filename or "")
    if ext not in config.ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or '<none>'}'. "
            f"Allowed: {', '.join(config.ALLOWED_EXTENSIONS)}."
        )
    return ext


# --------------------------------------------------------------------------- #
# Size helpers
# --------------------------------------------------------------------------- #

def enforce_size(byte_count: int) -> None:
    """Raise 413 when *byte_count* exceeds the configured limit."""
    if byte_count > config.MAX_UPLOAD_BYTES:
        raise FileTooLargeError(
            f"Upload is {byte_count} bytes; maximum is {config.MAX_UPLOAD_BYTES} bytes."
        )


# --------------------------------------------------------------------------- #
# Magic-byte validation
# --------------------------------------------------------------------------- #

def sniff_signature(head: bytes, ext: str) -> None:
    """Validate the first bytes of an uploaded file against its extension.

    ZIP files can legitimately start with any of three PK signatures:

    * ``PK\x03\x04`` -- local file header (a normal non-empty zip)
    * ``PK\x05\x06`` -- end-of-central-directory record (an empty zip)
    * ``PK\x07\x08`` -- ZIP64 EOCD locator

    All three are valid ZIP starts; rejecting an empty zip at this layer
    would push the failure into the geospatial reader, where it would surface
    as the (more useful) 422 "no Shapefile" message.  We accept all three
    here and let the reader take care of "no entries".
    """
    expected = config.ACCEPTED_SIGNATURES.get(ext)
    if expected is None:
        # Shouldn't happen -- extension is gated by validate_filename first.
        raise UnsupportedFileTypeError(f"Cannot validate extension '{ext}'.")

    if not any(head.startswith(sig) for sig in expected):
        raise InvalidUploadError(
            f"Uploaded .{ext.lstrip('.')} file has an invalid signature; the file is corrupt or mislabelled."
        )


# --------------------------------------------------------------------------- #
# Persisting the raw upload to a temporary location
# --------------------------------------------------------------------------- #

def save_upload_to_temp(content: bytes, filename: str, ext: str, tmp_dir: Path) -> Path:
    """Write the uploaded content to a deterministic temp path.

    The function takes *content* as bytes rather than a stream because the
    FastAPI route reads the whole upload into memory (capped at
    :data:`config.MAX_UPLOAD_BYTES`).  This is intentional: it lets us
    validate the magic bytes and the size up-front, before any parsing runs.
    """
    import uuid

    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    path = tmp_dir / safe_name
    path.write_bytes(content)
    return path
