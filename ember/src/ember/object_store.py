from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import logging
import shutil
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from minio import Minio
from minio.error import S3Error
from openai.types.responses.response_input_image_param import ResponseInputImageParam
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .config import ObjectStoreSettings

logger = logging.getLogger(__name__)


class ImageHandle(BaseModel):
    mime_type: str = Field(..., description="MIME type of the uploaded image.")
    size_bytes: int = Field(..., description="Size of the stored object in bytes.")
    storage_url: HttpUrl = Field(
        ..., description="Signed URL the model can fetch to retrieve the image."
    )
    expires_at: datetime = Field(
        ..., description="UTC timestamp indicating when the signed URL expires."
    )
    model_config = ConfigDict(frozen=True, extra="forbid")

    def to_responses_part(
        self, detail: Literal["auto", "low", "high"] = "auto"
    ) -> ResponseInputImageParam:
        return ResponseInputImageParam(
            type="input_image",
            image_url=str(self.storage_url),
            detail=detail,
        )


class ObjectStoreClient:
    """Thin wrapper around MinIO for uploading workspace artifacts."""

    def __init__(self, settings: ObjectStoreSettings) -> None:
        self._settings = settings
        self._expiry = max(1, min(settings.url_expiry_seconds, 7 * 24 * 60 * 60))
        self._staging_dir = settings.staging_dir.expanduser()
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._max_staging_bytes = settings.staging_max_bytes

    def upload_image(self, file_path: Path, mime_type: str) -> ImageHandle:
        access_key = self._settings.access_key_secret.value(required=True)
        secret_key = self._settings.secret_key_secret.value(required=True)
        client = self._build_client(access_key, secret_key)
        staged_path = self._stage_file(file_path)
        object_name = self._object_name(file_path)
        try:
            stat = staged_path.stat()
            with staged_path.open("rb") as handle:
                client.put_object(
                    self._settings.bucket,
                    object_name,
                    handle,
                    length=stat.st_size,
                    content_type=mime_type,
                )
        except S3Error as exc:
            raise RuntimeError(
                f"Failed to upload {file_path.name} to object store: {exc}"
            ) from exc
        finally:
            with contextlib.suppress(OSError):
                staged_path.unlink()

        expiry = timedelta(seconds=self._expiry)
        expires_at = datetime.now(timezone.utc) + expiry
        try:
            url = client.presigned_get_object(
                self._settings.bucket, object_name, expires=expiry
            )
        except S3Error as exc:
            raise RuntimeError(
                f"Failed to create presigned URL for {file_path.name}: {exc}"
            ) from exc

        return ImageHandle(
            mime_type=mime_type,
            size_bytes=stat.st_size,
            storage_url=url,
            expires_at=expires_at,
        )

    def _build_client(self, access_key: str, secret_key: str) -> Minio:
        parsed = urlparse(self._settings.endpoint)
        host = parsed.netloc or parsed.path
        if not host:
            raise RuntimeError(
                f"Invalid object store endpoint: {self._settings.endpoint}"
            )
        secure = bool(self._settings.secure)
        return Minio(
            host,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def _object_name(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        return f"ember/{uuid4().hex}{suffix}"

    def _stage_file(self, file_path: Path) -> Path:
        staged = self._staging_dir / f"{uuid4().hex}{file_path.suffix.lower()}"
        shutil.copyfile(file_path, staged)
        logger.debug("Staged image %s at %s", file_path, staged)
        self._enforce_staging_quota()
        return staged

    def _enforce_staging_quota(self) -> None:
        total = 0
        entries: list[tuple[float, Path, int]] = []
        for path in self._staging_dir.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            size = stat.st_size
            total += size
            entries.append((stat.st_mtime, path, size))

        if total <= self._max_staging_bytes:
            return

        for _, path, size in sorted(entries):
            if total <= self._max_staging_bytes:
                break
            with contextlib.suppress(OSError):
                path.unlink()
            total -= size
