import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = Path("C:/Program Files/Git/bin/bash.exe")


def _bash_path(path: Path) -> str:
    drive, tail = os.path.splitdrive(str(path.resolve()))
    return f"/{drive[0].lower()}{tail.replace('\\\\', '/')}"


@pytest.fixture
def git_bash() -> str:
    if os.name == "nt":
        pytest.skip("root-only Linux deployment scripts execute in the Linux canary runtime")
    if not BASH.is_file():
        pytest.skip("Git Bash is required for hermetic shell-script tests")
    return str(BASH)


@pytest.fixture
def script_tmp() -> Iterator[Path]:
    path = Path(tempfile.gettempdir()) / "recording-agent-canary-tests" / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _write_mock(directory: Path, name: str, body: str) -> None:
    target = directory / name
    target.write_text(f"#!/usr/bin/env bash\\nset -eu\\n{body}\\n", encoding="utf-8")
    target.chmod(0o755)


def _copy_deploy_for_test(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "canary"
    env_file = tmp_path / "backend.env"
    proxy_env_file = tmp_path / "notion-proxy.env"
    script = (ROOT / "deploy/scripts/canary-deploy.sh").read_text(encoding="utf-8")
    script = script.replace(
        "readonly ROOT=/opt/recording-agent-canary", f"readonly ROOT={_bash_path(root)}"
    )
    script = script.replace(
        "readonly ENV_FILE=/etc/recording-agent/canary/backend.env",
        f"readonly ENV_FILE={_bash_path(env_file)}",
    ).replace(
        "readonly PROXY_ENV_FILE=/etc/recording-agent/canary/notion-proxy.env",
        f"readonly PROXY_ENV_FILE={_bash_path(proxy_env_file)}",
    )
    script = script.replace(
        '[[ ${EUID} -eq 0 ]] || die "must be invoked by root"', ": # test root bypass"
    )
    script = script.replace("readonly MIN_AVAILABLE_KIB=1179648", "readonly MIN_AVAILABLE_KIB=0")
    copied = tmp_path / "canary-deploy.sh"
    copied.write_text(script, encoding="utf-8")
    copied.chmod(0o755)
    root.mkdir()
    env_file.write_text(
        "\\n".join(
            [
                "TEST_MODE_ENABLED=true",
                "SCHEDULER_ENABLED=false",
                "AUTONOMOUS_ROUTING_ENABLED=false",
                "NOTION_WRITES_ENABLED=false",
                "MATTERMOST_DELIVERY_ENABLED=false",
                "YANDEX_SOURCE_MUTATION_ENABLED=false",
                "STORAGE_PROVIDER=minio",
                "POSTGRES_DB=recording_agent_canary",
                "POSTGRES_USER=recording_agent_canary",
                'TEST_RECRUITER_ALLOWLIST=["test@example.invalid"]',
                'TEST_NOTION_DATABASE_ALLOWLIST=["00000000-0000-0000-0000-000000000001"]',
                "APP_PORT=18001",
            ]
        )
        + "\\n",
        encoding="utf-8",
    )
    proxy_env_file.write_text("VPN_SUB_URL=https://example.invalid/sub\\n", encoding="utf-8")
    return copied, root, env_file, proxy_env_file


def _deploy_env(tmp_path: Path, commit_from_image: str, disk_available: int) -> dict[str, str]:
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    log = tmp_path / "docker.log"
    _write_mock(
        mock_bin,
        "docker",
        f'''printf '%s\\n' "$*" >> "{_bash_path(log)}"
case "$*" in
  *"buildx imagetools inspect"*) printf '%s\\n' "{commit_from_image}" ;;
  *"ps --filter label=com.docker.compose.project=recording-agent"*) printf '%s\\n' production-id ;;
  *"inspect --format"*) printf '%s\\n' true ;;
esac''',
    )
    df_output = (
        "printf '%s\\n' 'Filesystem 1024-blocks Used Available Capacity Mounted on' "
        f"'/dev/mock 9999999 1 {disk_available} 1% /opt'"
    )
    _write_mock(mock_bin, "df", df_output)
    _write_mock(mock_bin, "stat", "printf '%s\\n' 600:root:root")
    _write_mock(mock_bin, "chown", ":")
    return os.environ | {
        "PATH": f"{_bash_path(mock_bin)}:{os.environ['PATH']}",
        "MOCK_DOCKER_LOG": _bash_path(log),
    }


def test_canary_deploy_rejects_wrong_oci_revision_before_compose_mutation(
    script_tmp: Path, git_bash: str
) -> None:
    script, *_ = _copy_deploy_for_test(script_tmp)
    commit = "a" * 40
    result = subprocess.run(
        [
            git_bash,
            _bash_path(script),
            commit,
            f"ghcr.io/seitovaralina/recording-agent@sha256:{'b' * 64}",
            "c" * 64,
        ],
        capture_output=True,
        check=False,
        env=_deploy_env(script_tmp, "d" * 40, 9_999_999),
        text=True,
    )

    assert result.returncode != 0
    assert "image revision does not match canary commit" in result.stderr
    assert "compose" not in (script_tmp / "docker.log").read_text(encoding="utf-8")


def test_canary_deploy_rejects_low_disk_before_archive_or_compose_mutation(
    script_tmp: Path, git_bash: str
) -> None:
    script, *_ = _copy_deploy_for_test(script_tmp)
    commit = "a" * 40
    result = subprocess.run(
        [
            git_bash,
            _bash_path(script),
            commit,
            f"ghcr.io/seitovaralina/recording-agent@sha256:{'b' * 64}",
            "c" * 64,
        ],
        capture_output=True,
        check=False,
        env=_deploy_env(script_tmp, commit, 1),
        text=True,
    )

    assert result.returncode != 0
    assert "disk capacity gate failed" in result.stderr
    assert "compose" not in (script_tmp / "docker.log").read_text(encoding="utf-8")


def test_canary_smoke_passes_one_allowlisted_database_id_to_schema_cli() -> None:
    script = (ROOT / "deploy/scripts/canary-smoke-test.sh").read_text(encoding="utf-8")

    assert "--test-only-schema" not in script
    assert '--database-id "$database_id"' in script
    assert "TEST_NOTION_DATABASE_ALLOWLIST" in script


def test_canary_deploy_binds_image_revision_and_gates_disk_capacity() -> None:
    script = (ROOT / "deploy/scripts/canary-deploy.sh").read_text(encoding="utf-8")

    assert "org.opencontainers.image.revision" in script
    assert '[[ $image_commit == "$commit" ]]' in script
    assert 'df -Pk "$ROOT_PARENT"' in script


def test_canary_build_sets_candidate_revision_label() -> None:
    workflow = (ROOT / ".github/workflows/canary-build.yml").read_text(encoding="utf-8")

    assert '--label "org.opencontainers.image.revision=${CANDIDATE_SHA}"' in workflow
