"""Durable Cloudinary backing store for student documents.

The existing documents table continues to store the local filepath. On hosts with
Cloudinary configured, the local file is mirrored as an authenticated raw asset
and can be restored into UPLOAD_FOLDER after a restart or deployment.
"""

import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url


MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class DocumentStorageError(RuntimeError):
    """Raised when durable document storage cannot complete an operation."""


def document_storage_configured():
    return all(
        (os.environ.get(name) or "").strip()
        for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
    )


def _configure_cloudinary():
    cloud_name = (os.environ.get("CLOUDINARY_CLOUD_NAME") or "").strip()
    api_key = (os.environ.get("CLOUDINARY_API_KEY") or "").strip()
    api_secret = (os.environ.get("CLOUDINARY_API_SECRET") or "").strip()
    if not cloud_name or not api_key or not api_secret:
        raise DocumentStorageError("Cloudinary document storage is not configured.")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def _basename(value):
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return ""
    return name


def _document_extension(filename):
    suffix = Path(_basename(filename)).suffix.lower()
    if not suffix or len(suffix) > 16 or not suffix[1:].isalnum():
        return ".bin"
    return suffix


def _public_id(document_id, storage_name):
    try:
        safe_id = int(document_id)
    except (TypeError, ValueError) as exc:
        raise DocumentStorageError("Invalid document id.") from exc
    if safe_id <= 0:
        raise DocumentStorageError("Invalid document id.")
    # Raw Cloudinary assets must include their extension in the public id.
    return f"nexora_document_{safe_id}{_document_extension(storage_name)}"


def _safe_current_path(upload_folder, storage_name):
    name = _basename(storage_name)
    if not upload_folder or not name:
        return None
    try:
        base = Path(upload_folder).resolve()
        candidate = (base / name).resolve()
        if candidate.parent != base:
            return None
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def mirror_document(document_id, filename, filepath):
    """Persist a local student document as an authenticated Cloudinary raw asset."""
    if not document_storage_configured():
        return False

    local_path = Path(filepath)
    if not local_path.is_file():
        raise DocumentStorageError("Local document does not exist.")
    try:
        size = local_path.stat().st_size
    except OSError as exc:
        raise DocumentStorageError("Unable to inspect local document.") from exc
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentStorageError("Document exceeds the supported 5 MB limit.")

    storage_name = _basename(filepath) or _basename(filename)
    _configure_cloudinary()
    try:
        cloudinary.uploader.upload(
            str(local_path),
            resource_type="raw",
            type="authenticated",
            public_id=_public_id(document_id, storage_name),
            overwrite=True,
            invalidate=True,
            unique_filename=False,
            use_filename=False,
            tags=["nexora", "student-document"],
        )
    except Exception as exc:
        raise DocumentStorageError("Unable to persist document in Cloudinary.") from exc
    return True


def ensure_document_local(document_id, filename, filepath, upload_folder):
    """Return a safe local path, restoring the document from Cloudinary if needed."""
    storage_name = _basename(filepath) or _basename(filename)
    target = _safe_current_path(upload_folder, storage_name)
    if target is None:
        return None

    # Accept an existing file only from the current configured upload directory.
    if target.is_file():
        return str(target)

    filename_target = _safe_current_path(upload_folder, filename)
    if filename_target is not None and filename_target.is_file():
        return str(filename_target)

    if not document_storage_configured():
        return None

    _configure_cloudinary()
    try:
        remote_url, _ = cloudinary_url(
            _public_id(document_id, storage_name),
            resource_type="raw",
            type="authenticated",
            secure=True,
            sign_url=True,
        )
        request = Request(remote_url, headers={"User-Agent": "Nexora/1.0"})
        with urlopen(request, timeout=15) as response:
            data = response.read(MAX_DOCUMENT_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, DocumentStorageError):
        return None
    except Exception:
        return None

    if not data or len(data) > MAX_DOCUMENT_BYTES:
        return None

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.cloudinary.tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    except OSError:
        return None

    return str(target)


def delete_document_backup(document_id, filename_or_path):
    """Delete a document's durable Cloudinary copy when the database row is deleted."""
    if not document_storage_configured():
        return False

    _configure_cloudinary()
    try:
        cloudinary.uploader.destroy(
            _public_id(document_id, filename_or_path),
            resource_type="raw",
            type="authenticated",
            invalidate=True,
        )
    except Exception as exc:
        raise DocumentStorageError("Unable to delete document from Cloudinary.") from exc
    return True
