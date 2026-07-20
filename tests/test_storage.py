from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services.storage import MinIOBackend, StorageFactory
from app.tools.synology import SynologyBackend


async def chunks() -> AsyncIterator[bytes]:
    yield b"abc"
    yield b"def"


class FakeS3:
    def __init__(self, fail_part: int | None = None) -> None:
        self.put_kwargs: dict[str, Any] = {}
        self.fail_part = fail_part
        self.uploaded_parts: list[dict[str, Any]] = []
        self.completed: dict[str, Any] | None = None
        self.aborted: dict[str, Any] | None = None

    async def put_object(self, **kwargs: Any) -> object:
        self.put_kwargs = kwargs
        return {}

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"Bucket": "bucket", "Key": "base/date/name/video.webm"}
        return {"UploadId": "upload-1"}

    async def upload_part(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["PartNumber"] == self.fail_part:
            raise RuntimeError("part upload failed")
        self.uploaded_parts.append(kwargs)
        return {"ETag": f"etag-{kwargs['PartNumber']}"}

    async def complete_multipart_upload(self, **kwargs: Any) -> object:
        self.completed = kwargs
        return {}

    async def abort_multipart_upload(self, **kwargs: Any) -> object:
        self.aborted = kwargs
        return {}

    async def generate_presigned_url(self, method: str, **kwargs: Any) -> str:
        assert method == "get_object"
        assert kwargs["ExpiresIn"] == 604800
        return "https://minio.test/presigned"


@pytest.mark.anyio
async def test_minio_multipart_upload_and_presigned_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.storage.MIN_MULTIPART_PART_SIZE", 4)
    s3 = FakeS3()
    backend = MinIOBackend("http://minio", "key", SecretStr("secret"), "bucket", s3)
    path = await backend.upload("/base/date/name", "video.webm", chunks(), 6)
    assert path == "/base/date/name/video.webm"
    assert [part["Body"] for part in s3.uploaded_parts] == [b"abcd", b"ef"]
    assert [part["PartNumber"] for part in s3.uploaded_parts] == [1, 2]
    assert s3.completed is not None
    assert s3.completed["Key"] == "base/date/name/video.webm"
    assert s3.completed["MultipartUpload"] == {
        "Parts": [
            {"ETag": "etag-1", "PartNumber": 1},
            {"ETag": "etag-2", "PartNumber": 2},
        ]
    }
    assert s3.aborted is None
    assert await backend.create_share_link(path) == "https://minio.test/presigned"


@pytest.mark.anyio
async def test_minio_aborts_multipart_upload_on_part_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.storage.MIN_MULTIPART_PART_SIZE", 4)
    s3 = FakeS3(fail_part=2)
    backend = MinIOBackend("http://minio", "key", SecretStr("secret"), "bucket", s3)

    with pytest.raises(RuntimeError, match="part upload failed"):
        await backend.upload("/base/date/name", "video.webm", chunks(), 6)

    assert s3.completed is None
    assert s3.aborted == {
        "Bucket": "bucket",
        "Key": "base/date/name/video.webm",
        "UploadId": "upload-1",
    }


def test_storage_factory_selects_provider() -> None:
    assert isinstance(StorageFactory.create(Settings(storage_provider="minio")), MinIOBackend)
    assert isinstance(StorageFactory.create(Settings(storage_provider="synology")), SynologyBackend)
