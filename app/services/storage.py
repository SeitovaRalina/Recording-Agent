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
    async def ensure_folder(self, path: str) -> None: ...

    async def upload(
        self,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
        size: int | None,
    ) -> str: ...

    async def create_share_link(self, path: str) -> str: ...


class StreamingUnsupportedError(RuntimeError):
    """Backend asks TransferService to retry through a temporary file."""


class _S3Client(Protocol):
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

    async def ensure_folder(self, path: str) -> None:
        del path

    async def upload(
        self,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
        size: int | None,
    ) -> str:
        del size
        key = f"{folder.rstrip('/')}/{filename}".lstrip("/")
        async with self._client_scope() as client:
            created = await client.create_multipart_upload(Bucket=self._bucket, Key=key)
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
                    await client.put_object(Bucket=self._bucket, Key=key, Body=b"")
                    return f"/{key}"
                await client.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except Exception:
                try:
                    await client.abort_multipart_upload(
                        Bucket=self._bucket, Key=key, UploadId=upload_id
                    )
                except Exception:
                    pass
                raise
        return f"/{key}"

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
            )
        return MinIOBackend(
            settings.minio_endpoint,
            settings.minio_access_key,
            settings.minio_secret_key,
            settings.minio_bucket,
        )
