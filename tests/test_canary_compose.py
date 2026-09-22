from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_canary_compose_uses_only_canary_resources_and_private_proxy_network() -> None:
    compose = yaml.safe_load((ROOT / "compose.canary.yml").read_text(encoding="utf-8"))

    assert compose["name"] == "recording-agent-canary"
    assert compose["volumes"]["canary-postgres-data"]["name"] == "recording-agent-canary-postgres"
    assert compose["networks"]["canary-backend"]["internal"] is True
    assert compose["networks"]["canary-notion-proxy"]["internal"] is True
    assert compose["networks"]["canary-notion-egress"]["internal"] is False
    assert compose["services"]["notion-proxy"].get("ports") is None


def test_canary_backend_effects_are_disabled_and_it_only_reaches_proxy() -> None:
    compose = yaml.safe_load((ROOT / "compose.canary.yml").read_text(encoding="utf-8"))
    backend = compose["services"]["backend"]

    assert backend["environment"]["NOTION_PROXY_URL"] == "http://notion-proxy:7890"
    assert backend["environment"]["TEST_MODE_ENABLED"] == "true"
    for flag in (
        "SCHEDULER_ENABLED",
        "AUTONOMOUS_ROUTING_ENABLED",
        "YANDEX_SOURCE_MUTATION_ENABLED",
        "NOTION_WRITES_ENABLED",
        "MATTERMOST_DELIVERY_ENABLED",
    ):
        assert backend["environment"][flag] == "false"
    assert set(backend["networks"]) == {"canary-backend", "canary-notion-proxy"}
