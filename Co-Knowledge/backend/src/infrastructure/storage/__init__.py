"""Knowledge-base file storage backends (local volume / MinIO)."""

from infrastructure.storage.backend import (  # noqa: F401
    BACKEND_LOCAL,
    BACKEND_MINIO,
    LocalBackend,
    MinioBackend,
    backend_name,
    local_root,
    normalize_key,
    reset_storage_backend,
    scratch_root,
    set_storage_backend,
    storage_backend,
)
