from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_canary_build_has_no_host_or_vpn_secret_channel() -> None:
    workflow = (ROOT / ".github/workflows/canary-build.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "commit_sha" in workflow
    assert "environment:" not in workflow
    assert "VPN_SUB_URL" not in workflow
    assert "ssh " not in workflow
    assert "scp " not in workflow


def test_canary_build_rejects_main_and_reports_only_pinned_image() -> None:
    workflow = (ROOT / ".github/workflows/canary-build.yml").read_text(encoding="utf-8")

    assert "^[0-9a-f]{40}$" in workflow
    assert "Candidate is reachable from main" in workflow
    assert 'image="${IMAGE_NAME}@${digest}"' in workflow
    assert "--provenance=mode=max" in workflow
