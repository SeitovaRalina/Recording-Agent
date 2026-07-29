import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_event_accepted_with_valid_secret(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/events",
        headers={"X-OpenClaw-Secret": "test-secret"},  # pragma: allowlist secret
        json={"type": "recording_found", "payload": {"recording_id": "123"}},
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": True}


@pytest.mark.anyio
@pytest.mark.parametrize("secret", [None, "wrong-secret"])  # pragma: allowlist secret
async def test_event_rejects_invalid_secret(async_client: AsyncClient, secret: str | None) -> None:
    headers = {} if secret is None else {"X-OpenClaw-Secret": secret}
    response = await async_client.post("/events", headers=headers, json={"type": "recording_found"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_event_requires_type(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/events",
        headers={"X-OpenClaw-Secret": "test-secret"},  # pragma: allowlist secret
        json={"payload": {}},
    )
    assert response.status_code == 422
