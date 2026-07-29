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
    def __init__(
        self,
        fail_part: int | None = None,
        existing: dict[str, Any] | None = None,
    ) -> None:
        self.put_kwargs: dict[str, Any] = {}
        self.fail_part = fail_part
        self.uploaded_parts: list[dict[str, Any]] = []
        self.completed: dict[str, Any] | None = None
        self.aborted: dict[str, Any] | None = None
        self.existing = existing

    async def head_object(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        if self.existing is None:
            error = RuntimeError("not found")
            error.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
            raise error
        return self.existing

    async def put_object(self, **kwargs: Any) -> object:
        self.put_kwargs = kwargs
        return {}

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {
            "Bucket": "bucket",
            "Key": "base/date/name/video.webm",
            "Metadata": {"recording-id": "recording-1", "content-identity": "md5-1"},
        }
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
    path = await backend.upload(
        "/base/date/name",
        "video.webm",
        chunks(),
        6,
        recording_id="recording-1",
        content_identity="md5-1",
    )
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
    assert s3.completed["IfNoneMatch"] == "*"
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
        await backend.upload(
            "/base/date/name",
            "video.webm",
            chunks(),
            6,
            recording_id="recording-1",
            content_identity="md5-1",
        )

    assert s3.completed is None
    assert s3.aborted == {
        "Bucket": "bucket",
        "Key": "base/date/name/video.webm",
        "UploadId": "upload-1",
    }


@pytest.mark.anyio
async def test_minio_reuses_object_owned_by_same_recording_without_upload() -> None:
    s3 = FakeS3(existing={"Metadata": {"recording-id": "recording-1", "content-identity": "md5-1"}})
    backend = MinIOBackend("http://minio", "key", SecretStr("secret"), "bucket", s3)

    path = await backend.upload(
        "/base/date/name",
        "video.webm",
        chunks(),
        6,
        recording_id="recording-1",
        content_identity="md5-1",
    )

    assert path == "/base/date/name/video.webm"
    assert s3.uploaded_parts == []
    assert s3.completed is None


@pytest.mark.anyio
async def test_minio_rejects_existing_key_owned_by_another_recording() -> None:
    s3 = FakeS3(existing={"Metadata": {"recording-id": "recording-2", "content-identity": "md5-2"}})
    backend = MinIOBackend("http://minio", "key", SecretStr("secret"), "bucket", s3)

    with pytest.raises(RuntimeError, match="already exists"):
        await backend.upload(
            "/base/date/name",
            "video.webm",
            chunks(),
            6,
            recording_id="recording-1",
            content_identity="md5-1",
        )

    assert s3.uploaded_parts == []
    assert s3.completed is None


def test_storage_factory_selects_provider() -> None:
    minio = StorageFactory.create(Settings(storage_provider="minio"))
    synology = StorageFactory.create(
        Settings(
            storage_provider="synology",
            synology_base_url="https://nas.test",
            synology_user="operator",
            synology_pass=SecretStr("password"),
            synology_interview_roots=("/home/Recruiting-E/2. Interviews external",),
        )
    )
    assert isinstance(minio, MinIOBackend)
    assert minio.durable_for_source_cleanup is False
    assert isinstance(synology, SynologyBackend)
    assert synology.durable_for_source_cleanup is True
