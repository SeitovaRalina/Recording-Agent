from pathlib import Path
import os
import subprocess
import tempfile

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
    assert "ports" not in proxy
    assert proxy["env_file"] == ["/etc/recording-agent/notion-proxy.env"]
    assert backend["depends_on"]["notion-proxy"]["condition"] == "service_healthy"


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

    assert 'MIHOMO_IMAGE=$(sed -n \'s/^MIHOMO_IMAGE=//p\' "$ENV_FILE")' in deploy
    assert (
        '[[ $MIHOMO_IMAGE =~ '
        '^ghcr\\.io/metacubex/mihomo@sha256:[0-9a-f]{64}$ ]]' in deploy
    )


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
        Path(render_compose.name).unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr


def test_mihomo_config_routes_only_notion_through_tunnel() -> None:
    config = (ROOT / "deploy" / "mihomo" / "config.yaml").read_text(encoding="utf-8")

    assert "DOMAIN,api.notion.com,NOTION" in config
    assert "MATCH,DIRECT" in config
    assert "__VPN_SUB_URL__" in config
    assert "external-controller" not in config


def test_readiness_rejects_cloudflare_html() -> None:
    entrypoint = (ROOT / "deploy" / "mihomo" / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'grep -q \'"object":"error"\' "$response_file"' in entrypoint
    assert "! grep -qiE 'cloudflare|<html' \"$response_file\"" in entrypoint
