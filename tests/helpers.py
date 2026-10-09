"""Shared HTTP helper for tests."""

from __future__ import annotations


def upload_file(client, path, filename=None):
    """POST a file to /api/files/ with multipart field name 'file'."""
    import os
    fname = filename or os.path.basename(path)
    with open(path, "rb") as fp:
        data = fp.read()
    return client.post(
        "/api/files/",
        files={"file": (fname, data, "application/octet-stream")},
    )
