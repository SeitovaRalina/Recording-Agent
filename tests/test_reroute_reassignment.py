import pytest

from app.db.models.recording_storage_artifact import RecordingStorageArtifact
from app.services.reroute import RerouteRejectedError, _allowed_root
from app.tools.notion import _canonical_notion_page_id
from app.tools.synology import _copy_move_task_id


def test_copy_move_task_requires_explicit_task_identity() -> None:
    assert _copy_move_task_id({"data": {"taskid": "task-1"}}) == "task-1"
    assert _copy_move_task_id({"data": {}}) is None
    assert _copy_move_task_id({"data": []}) is None


def test_reroute_confines_each_end_to_an_allowed_root() -> None:
    roots = ("/home/E/2. Interviews external", "/home/E/3. Interviews internal")
    assert _allowed_root(roots, "/home/E/2. Interviews external/Python/v.webm") == roots[0]
    assert _allowed_root(roots, "/home/E/3. Interviews internal/Flutter") == roots[1]
    with pytest.raises(RerouteRejectedError):
        _allowed_root(roots, "/outside/file.webm")


def test_reassignment_url_page_id_is_canonicalized() -> None:
    raw = "00000000000000000000000000000001"
    assert _canonical_notion_page_id(raw) == "00000000-0000-0000-0000-000000000001"
    assert _canonical_notion_page_id("not-a-page") is None
    assert (
        _canonical_notion_page_id(
            "https://app.notion.com/p/E2E-R10-0924_1a1-3e5c8889e4c881afa4cde62fdd682c25?v=abc"
        )
        == "3e5c8889-e4c8-81af-a4cd-e62fdd682c25"
    )
    assert (
        _canonical_notion_page_id("https://www.notion.so/team/3e5c8889-e4c8-81af-a4cd-e62fdd682c25")
        == "3e5c8889-e4c8-81af-a4cd-e62fdd682c25"
    )
    assert _canonical_notion_page_id("https://app.notion.com/p/no-id-here") is None


def test_artifact_history_marks_one_placement_active() -> None:
    artifact = RecordingStorageArtifact(
        folder_path="/allowed/target",
        file_path="/allowed/target/file.webm",
        share_url="https://share.test/file",
        owner_marker_path="/allowed/target/.file.webm.recording-agent-owner.json",
        is_active=True,
    )
    assert artifact.is_active is True
