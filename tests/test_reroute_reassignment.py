import pytest

from app.db.models.recording_storage_artifact import RecordingStorageArtifact
from app.services.reroute import RerouteRejectedError, _shared_allowed_root
from app.tools.notion import _canonical_notion_page_id
from app.tools.synology import _copy_move_task_id


def test_copy_move_task_requires_explicit_task_identity() -> None:
    assert _copy_move_task_id({"data": {"taskid": "task-1"}}) == "task-1"
    assert _copy_move_task_id({"data": {}}) is None
    assert _copy_move_task_id({"data": []}) is None


def test_reroute_rejects_source_target_without_shared_allowed_root() -> None:
    with pytest.raises(RerouteRejectedError):
        _shared_allowed_root(("/allowed",), "/outside/file.webm", "/allowed/target")


def test_reassignment_url_page_id_is_canonicalized() -> None:
    raw = "41cfe300f31183929e6301ffe4bf20fa"
    assert _canonical_notion_page_id(raw) == "41cfe300-f311-8392-9e63-01ffe4bf20fa"
    assert _canonical_notion_page_id("not-a-page") is None


def test_artifact_history_marks_one_placement_active() -> None:
    artifact = RecordingStorageArtifact(
        folder_path="/allowed/target",
        file_path="/allowed/target/file.webm",
        share_url="https://share.test/file",
        owner_marker_path="/allowed/target/.file.webm.recording-agent-owner.json",
        is_active=True,
    )
    assert artifact.is_active is True
