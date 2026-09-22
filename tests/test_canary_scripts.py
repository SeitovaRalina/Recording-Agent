from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_canary_smoke_passes_one_allowlisted_database_id_to_schema_cli() -> None:
    script = (ROOT / "deploy/scripts/canary-smoke-test.sh").read_text(encoding="utf-8")

    assert "--test-only-schema" not in script
    assert "--database-id \"$database_id\"" in script
    assert "TEST_NOTION_DATABASE_ALLOWLIST" in script


def test_canary_deploy_binds_image_revision_and_gates_disk_capacity() -> None:
    script = (ROOT / "deploy/scripts/canary-deploy.sh").read_text(encoding="utf-8")

    assert 'org.opencontainers.image.revision' in script
    assert '[[ $image_commit == "$commit" ]]' in script
    assert 'df -Pk "$ROOT_PARENT"' in script


def test_canary_build_sets_candidate_revision_label() -> None:
    workflow = (ROOT / ".github/workflows/canary-build.yml").read_text(encoding="utf-8")

    assert '--label "org.opencontainers.image.revision=${CANDIDATE_SHA}"' in workflow
