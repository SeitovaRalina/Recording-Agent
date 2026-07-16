import logging

from app.config import Settings
from app.services.pipeline_trace import safe_url, trace


def test_trace_requires_explicit_development_opt_in(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="recording_agent.pipeline"):
        trace(
            Settings(app_environment="production", pipeline_trace_enabled=True),
            "pipeline.test",
            candidate_name="Ivan",
        )

    assert "PIPELINE_TRACE" not in caplog.text


def test_trace_redacts_sensitive_values_and_signed_url_query(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="recording_agent.pipeline"):
        trace(
            Settings(app_environment="development", pipeline_trace_enabled=True),
            "pipeline.test",
            token="must-not-appear",
            share_url=safe_url("https://minio.test/path/video.webm?X-Amz-Signature=secret"),
        )

    assert "PIPELINE_TRACE" in caplog.text
    assert "must-not-appear" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text
    assert "https://minio.test/path/video.webm?<redacted>" in caplog.text
