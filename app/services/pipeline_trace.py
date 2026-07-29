import json
import logging
from datetime import date, datetime
from enum import Enum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.config import Settings

logger = logging.getLogger("recording_agent.pipeline")

_SENSITIVE_KEY_PARTS = ("authorization", "password", "secret", "token", "raw_ics")


def trace(settings: Settings, event: str, **fields: object) -> None:
    """Emit a structured pipeline trace only in explicitly enabled development mode."""
    if not settings.pipeline_trace_active:
        return
    payload = {"event": event, **{key: _safe_value(key, value) for key, value in fields.items()}}
    logger.info("PIPELINE_TRACE %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def safe_url(value: str | None) -> str | None:
    """Keep a useful URL location while removing signed query parameters and fragments."""
    if not value:
        return value
    parsed = urlsplit(value)
    query = "<redacted>" if parsed.query else ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _safe_value(key: str, value: object) -> Any:
    lowered = key.casefold()
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
