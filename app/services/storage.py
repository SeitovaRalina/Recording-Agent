from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any, Protocol, cast

import httpx
from pydantic import SecretStr

from app.config import Settings

MIN_MULTIPART_PART_SIZE = 5 * 1024 * 1024


class StorageBackend(Protocol):
    @property
    def durable_for_source_cleanup(self) -> bool: ...

    async def ensure_folder(self, path: str) -> None: ...

    async def upload(
        self,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
        size: int | None,
        *,
        recording_id: str,
        content_identity: str,
    ) -> str: ...

    async def create_share_link(self, path: str) -> str: ...


class StreamingUnsupportedError(RuntimeError):
    """Backend asks TransferService to retry through a temporary file."""


class StorageCollisionError(RuntimeError):
    """Object key is already owned by another recording or content identity."""


class _S3Client(Protocol):
    async def head_object(self, **kwargs: Any) -> dict[str, Any]: ...

    async def put_object(self, **kwargs: Any) -> object: ...

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...

    async def upload_part(self, **kwargs: Any) -> dict[str, Any]: ...

    async def complete_multipart_upload(self, **kwargs: Any) -> object: ...

    async def abort_multipart_upload(self, **kwargs: Any) -> object: ...

    async def generate_presigned_url(self, method: str, **kwargs: Any) -> str: ...


class MinIOBackend:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: SecretStr,
        bucket: str,
        client: _S3Client | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._client = client

    @property
    def durable_for_source_cleanup(self) -> bool:
        return False

    async def ensure_folder(self, path: str) -> None:
        del path

    async def upload(
        self,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
        size: int | None,
        *,
        recording_id: str,
        content_identity: str,
    ) -> str:
        key = f"{folder.rstrip('/')}/{filename}".lstrip("/")
        metadata = {
            "recording-id": recording_id,
            "content-identity": content_identity,
        }
        async with self._client_scope() as client:
            existing = await self._head_object(client, key)
            if existing is not None:
                self._require_same_owner(key, existing, metadata, size)
                return f"/{key}"
            created = await client.create_multipart_upload(
                Bucket=self._bucket, Key=key, Metadata=metadata
            )
            upload_id = created.get("UploadId")
            if not isinstance(upload_id, str) or not upload_id:
                raise RuntimeError("S3 multipart upload returned no UploadId")
            parts: list[dict[str, object]] = []
            buffer = bytearray()
            try:
                async for chunk in stream:
                    offset = 0
                    while offset < len(chunk):
                        take = min(MIN_MULTIPART_PART_SIZE - len(buffer), len(chunk) - offset)
                        buffer.extend(chunk[offset : offset + take])
                        offset += take
                        if len(buffer) == MIN_MULTIPART_PART_SIZE:
                            parts.append(
                                await self._upload_part(
                                    client, key, upload_id, len(parts) + 1, bytes(buffer)
                                )
                            )
                            buffer.clear()
                if buffer:
                    parts.append(
                        await self._upload_part(
                            client, key, upload_id, len(parts) + 1, bytes(buffer)
                        )
                    )
                if not parts:
                    await client.abort_multipart_upload(
                        Bucket=self._bucket, Key=key, UploadId=upload_id
                    )
                    try:
                        await client.put_object(
                            Bucket=self._bucket,
                            Key=key,
                            Body=b"",
                            Metadata=metadata,
                            IfNoneMatch="*",
                        )
                    except Exception:
                        existing = await self._head_object(client, key)
                        if existing is None:
                            raise
                        self._require_same_owner(key, existing, metadata, size)
                    return f"/{key}"
                try:
                    await client.complete_multipart_upload(
                        Bucket=self._bucket,
                        Key=key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                        IfNoneMatch="*",
                    )
                except Exception:
                    try:
                        await client.abort_multipart_upload(
                            Bucket=self._bucket, Key=key, UploadId=upload_id
                        )
                    except Exception:
                        pass
                    existing = await self._head_object(client, key)
                    if existing is None:
                        raise
                    self._require_same_owner(key, existing, metadata, size)
            except Exception:
                try:
                    await client.abort_multipart_upload(
                        Bucket=self._bucket, Key=key, UploadId=upload_id
                    )
                except Exception:
                    pass
                raise
        return f"/{key}"

    async def _head_object(self, client: _S3Client, key: str) -> dict[str, Any] | None:
        try:
            return await client.head_object(Bucket=self._bucket, Key=key)
        except Exception as error:
            response = getattr(error, "response", None)
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if str(code) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    @staticmethod
    def _require_same_owner(
        key: str,
        existing: dict[str, Any],
        expected_metadata: dict[str, str],
        expected_size: int | None,
    ) -> None:
        metadata = existing.get("Metadata")
        content_length = existing.get("ContentLength")
        same_size = (
            expected_size is None or content_length is None or content_length == expected_size
        )
        same_owner = isinstance(metadata, dict) and all(
            metadata.get(name) == value for name, value in expected_metadata.items()
        )
        if same_owner and same_size:
            return
        raise StorageCollisionError(f"Storage key already exists with different ownership: {key}")

    async def _upload_part(
        self,
        client: _S3Client,
        key: str,
        upload_id: str,
        part_number: int,
        body: bytes,
    ) -> dict[str, object]:
        response = await client.upload_part(
            Bucket=self._bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=body,
        )
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise RuntimeError(f"S3 multipart part {part_number} returned no ETag")
        return {"ETag": etag, "PartNumber": part_number}

    async def create_share_link(self, path: str) -> str:
        key = path.lstrip("/")
        async with self._client_scope() as client:
            return await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=604800,
            )

    @asynccontextmanager
    async def _client_scope(self) -> AsyncIterator[_S3Client]:
        if self._client is not None:
            yield self._client
            return
        session_module = import_module("aiobotocore.session")
        session = session_module.get_session()
        context = session.create_client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key.get_secret_value(),
        )
        async with context as client:
            yield cast(_S3Client, client)


class StorageFactory:
    @staticmethod
    def create(settings: Settings, http_client: httpx.AsyncClient | None = None) -> StorageBackend:
        if settings.storage_provider == "synology":
            from app.tools.synology import SynologyBackend

            return SynologyBackend(
                settings.synology_base_url,
                settings.synology_api_key,
                http_client or httpx.AsyncClient(),
                username=settings.synology_user,
                password=settings.synology_pass,
                device_id=settings.synology_device_id,
            )
        return MinIOBackend(
            settings.minio_endpoint,
            settings.minio_access_key,
            settings.minio_secret_key,
            settings.minio_bucket,
        )
