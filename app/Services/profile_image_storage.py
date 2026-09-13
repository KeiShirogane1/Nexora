"""Cloudinary persistence for Nexora profile pictures.

Nexora keeps its existing profile-picture filenames and authenticated serving
routes. Cloudinary is the durable backing store while Render's local upload
folder acts as a disposable cache.
"""

from hashlib import sha256
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url


MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024


class ProfileImageStorageError(RuntimeError):
    """Raised when the durable profile-image store cannot be used."""


def _configure_cloudinary():
    cloud_name = (os.environ.get("CLOUDINARY_CLOUD_NAME") or "").strip()
    api_key = (os.environ.get("CLOUDINARY_API_KEY") or "").strip()
    api_secret = (os.environ.get("CLOUDINARY_API_SECRET") or "").strip()

    if not cloud_name or not api_key or not api_secret:
        raise ProfileImageStorageError("Cloudinary profile storage is not configured.")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def _safe_filename(filename):
    value = str(filename or "").strip()
    if not value or Path(value).name != value:
        raise ProfileImageStorageError("Invalid profile-picture filename.")
    return value


def _public_id(filename):
    safe_name = _safe_filename(filename)
    digest = sha256(safe_name.encode("utf-8")).hexdigest()[:32]
    return f"nexora_profile_{digest}"


def mirror_profile_picture(filename, upload_folder):
    """Upload the local profile image to Cloudinary under a stable asset id."""
    safe_name = _safe_filename(filename)
    local_path = Path(upload_folder) / safe_name
    if not local_path.is_file():
        raise ProfileImageStorageError("Local profile picture does not exist.")

    _configure_cloudinary()
    try:
        cloudinary.uploader.upload(
            str(local_path),
            public_id=_public_id(safe_name),
            overwrite=True,
            invalidate=True,
            unique_filename=False,
            use_filename=False,
            resource_type="image",
            tags=["nexora", "profile-picture"],
        )
    except Exception as exc:
        raise ProfileImageStorageError("Unable to persist profile picture in Cloudinary.") from exc

    return True


def profile_picture_cdn_url(filename):
    """Build the Cloudinary CDN URL for a stored profile filename without I/O."""
    try:
        safe_name = _safe_filename(filename)
    except ProfileImageStorageError:
        return ""

    cloud_name = (os.environ.get("CLOUDINARY_CLOUD_NAME") or "").strip()
    if not cloud_name:
        return ""

    try:
        cloudinary.config(cloud_name=cloud_name, secure=True)
        remote_url, _ = cloudinary_url(
            _public_id(safe_name),
            secure=True,
            resource_type="image",
            format="jpg",
            quality="auto",
        )
        return str(remote_url or "")
    except Exception:
        return ""


def ensure_profile_picture_local(filename, upload_folder):
    """Restore a missing Render-local profile picture from Cloudinary.

    Existing Nexora templates and routes can continue serving the same filename.
    The restored copy is normalized to JPEG bytes, matching the current profile
    upload naming convention used by Student and Supervisor accounts.
    """
    try:
        safe_name = _safe_filename(filename)
    except ProfileImageStorageError:
        return False

    folder = Path(upload_folder)
    local_path = folder / safe_name
    if local_path.is_file():
        return True

    try:
        _configure_cloudinary()
        remote_url, _ = cloudinary_url(
            _public_id(safe_name),
            secure=True,
            resource_type="image",
            format="jpg",
            quality="auto",
        )
        request = Request(remote_url, headers={"User-Agent": "Nexora/1.0"})
        with urlopen(request, timeout=10) as response:
            data = response.read(MAX_PROFILE_IMAGE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ProfileImageStorageError):
        return False
    except Exception:
        return False

    if not data or len(data) > MAX_PROFILE_IMAGE_BYTES:
        return False
    if not data.startswith(b"\xff\xd8\xff"):
        return False

    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = local_path.with_name(f".{local_path.name}.cloudinary.tmp")
        temporary.write_bytes(data)
        temporary.replace(local_path)
    except OSError:
        return False

    return True
