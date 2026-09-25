import os
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "compose.prod.yml").read_text(encoding="utf-8"))


def test_production_compose_isolates_notion_proxy() -> None:
    compose = _compose()
    services = compose["services"]
    backend = services["backend"]
    proxy = services["notion-proxy"]

    assert backend["environment"]["NOTION_PROXY_URL"] == "http://notion-proxy:7890"
    assert services["migrate"]["environment"]["NOTION_PROXY_URL"] == "http://notion-proxy:7890"
    assert "ports" not in proxy
    assert proxy["env_file"] == ["/etc/recording-agent/notion-proxy.env"]
    assert {
        "type": "bind",
        "source": "/etc/recording-agent/notion-koala-profile.yaml",
        "target": "/etc/mihomo/koala-profile.yaml",
        "read_only": True,
    } in proxy["volumes"]
    assert backend["depends_on"]["notion-proxy"]["condition"] == "service_healthy"


def test_production_effect_flags_come_from_env_file_and_default_off() -> None:
    environment = _compose()["services"]["backend"]["environment"]

    assert environment["TEST_MODE_ENABLED"] == "false"
    assert environment["PIPELINE_TRACE_ENABLED"] == "false"
    for flag in (
        "SCHEDULER_ENABLED",
        "YANDEX_SOURCE_MUTATION_ENABLED",
        "NOTION_WRITES_ENABLED",
        "MATTERMOST_DELIVERY_ENABLED",
    ):
        assert environment[flag] == f"${{{flag}:-false}}"


def test_proxy_network_cannot_reach_backend_or_postgres() -> None:
    compose = _compose()
    services = compose["services"]

    assert set(services["backend"]["networks"]) == {"backend", "notion-proxy"}
    assert set(services["notion-proxy"]["networks"]) == {
        "notion-egress",
        "notion-proxy",
    }
    assert compose["networks"]["notion-proxy"]["internal"] is True
    assert compose["networks"]["notion-egress"]["internal"] is False


def test_mihomo_image_is_allowlisted_immutable_digest() -> None:
    deploy = (ROOT / "deploy" / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    template = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    canary_build = (ROOT / ".github" / "workflows" / "canary-build.yml").read_text(
        encoding="utf-8"
    )

    assert 'MIHOMO_IMAGE=$(sed -n \'s/^MIHOMO_IMAGE=//p\' "$ENV_FILE")' in deploy
    assert (
        '[[ $MIHOMO_IMAGE =~ '
        '^docker\\.io/metacubex/mihomo@sha256:[0-9a-f]{64}$ ]]' in deploy
    )
    assert "docker.io/metacubex/mihomo@sha256:" in template
    assert "docker.io/metacubex/mihomo@sha256:" in canary_build
    assert "ghcr.io/metacubex/mihomo" not in "\n".join((deploy, template, canary_build))


def test_production_compose_renders() -> None:
    proxy_env = tempfile.NamedTemporaryFile(
        dir=ROOT,
        encoding="utf-8",
        mode="w",
        suffix=".env",
        delete=False,
    )
    proxy_env.write("VPN_SUB_URL=https://example.invalid/subscription\n")
    proxy_env.close()
    profile = tempfile.NamedTemporaryFile(
        dir=ROOT,
        encoding="utf-8",
        mode="w",
        suffix=".yaml",
        delete=False,
    )
    profile.write("proxies: []\nproxy-groups: []\nrules: []\n")
    profile.close()
    render_compose = tempfile.NamedTemporaryFile(
        dir=ROOT,
        encoding="utf-8",
        mode="w",
        suffix=".yml",
        delete=False,
    )
    render_compose.write(
        (ROOT / "compose.prod.yml")
        .read_text(encoding="utf-8")
        .replace("/etc/recording-agent/notion-proxy.env", proxy_env.name)
        .replace("/etc/recording-agent/notion-koala-profile.yaml", profile.name)
    )
    render_compose.close()
    environment = os.environ | {
        "RECORDING_AGENT_ENV_FILE": str(ROOT / ".env.production.example"),
    }
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ROOT / ".env.production.example"),
                "--file",
                render_compose.name,
                "config",
                "--quiet",
            ],
            capture_output=True,
            check=False,
            cwd=ROOT,
            env=environment,
            text=True,
        )
    finally:
        Path(proxy_env.name).unlink(missing_ok=True)
        Path(profile.name).unlink(missing_ok=True)
        Path(render_compose.name).unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr


def test_mihomo_config_routes_only_notion_through_tunnel() -> None:
    config = (ROOT / "deploy" / "mihomo" / "config.yaml").read_text(encoding="utf-8")

    assert "DOMAIN,api.notion.com,NOTION" in config
    assert "MATCH,DIRECT" in config
    assert "__VPN_SUB_URL__" in config
    assert "external-controller" not in config


def test_readiness_requires_a_live_mihomo_process() -> None:
    entrypoint = (ROOT / "deploy" / "mihomo" / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'kill -0 "$mihomo_pid" 2>/dev/null || fail "Mihomo exited during startup"' in entrypoint
    assert ': >"$readiness_marker"' in entrypoint
    assert "curl --" not in entrypoint


def test_entrypoint_prefers_koala_profile_file_with_backend_overrides() -> None:
    entrypoint = (ROOT / "deploy" / "mihomo" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "readonly profile=/etc/mihomo/koala-profile.yaml" in entrypoint
    assert 'if [ -s "$profile" ]; then' in entrypoint
    assert 'print "allow-lan: true"' in entrypoint
    assert 'print "mode: rule"' in entrypoint
    assert "[ -n \"${VPN_SUB_URL:-}\" ] || fail \"VPN_SUB_URL is required\"" in entrypoint


def test_deploy_starts_notion_proxy_before_backend_and_rolls_it_back() -> None:
    deploy = (ROOT / "deploy" / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "deploy" / "scripts" / "smoke-test.sh").read_text(encoding="utf-8")

    assert "readonly NOTION_PROFILE_FILE=/etc/recording-agent/notion-koala-profile.yaml" in deploy
    assert 'stat -c \'%a:%U:%g\' "$NOTION_PROFILE_FILE"' in deploy
    assert '"${compose[@]}" up -d --wait --wait-timeout 70 notion-proxy' in deploy
    assert '"${previous_compose[@]}" up -d --wait --wait-timeout 70 notion-proxy' in deploy
    assert 'ps --status running --quiet notion-proxy' in smoke


def test_entrypoint_uses_mihomo_binary_from_official_image() -> None:
    entrypoint = (ROOT / "deploy" / "mihomo" / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'if /mihomo -d "$runtime_dir" -t -f "$next_config"' in entrypoint
    assert '/mihomo -d "$runtime_dir" -f "$runtime_config" &' in entrypoint
