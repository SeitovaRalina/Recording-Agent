from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath

RESERVED = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
ALLOWED_EXTENSIONS = frozenset({"webm", "mp4", "mov", "mkv", "mp3", "m4a", "wav"})
MAX_COMPONENT = 100
MAX_KEY = 512


class FilenameError(ValueError):
    pass


@dataclass(frozen=True)
class StorageIdentity:
    filename: str
    key: str


def sanitize_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = WHITESPACE.sub(" ", normalized).strip(" .")
    normalized = RESERVED.sub("_", normalized)
    normalized = WHITESPACE.sub("_", normalized).strip(" ._")
    if not normalized:
        raise FilenameError("Filename component is empty after sanitization")
    return normalized[:MAX_COMPONENT].rstrip(" ._")


def build_storage_identity(
    *,
    event_date: date,
    candidate_name: str,
    project_or_spot: str | None,
    interview_type: str,
    original_filename: str,
    recruiter_prefix: str,
    key_prefix: str | None = None,
) -> StorageIdentity:
    extension = PurePath(original_filename).suffix.lstrip(".").lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FilenameError("Recording extension is not allowed")
    candidate = sanitize_component(candidate_name)
    project_value = (
        "unspecified" if project_or_spot is None or not project_or_spot.strip() else project_or_spot
    )
    project = sanitize_component(project_value)
    kind = sanitize_component(interview_type)
    recruiter = sanitize_component(recruiter_prefix)
    stamp = event_date.isoformat()
    filename = f"{stamp}_{candidate}_{project}_{kind}.{extension}"
    logical_key = f"{recruiter}/{stamp}/{candidate}/{filename}"
    if key_prefix:
        prefix = "/".join(sanitize_component(part) for part in key_prefix.split("/") if part)
        if not prefix:
            raise FilenameError("Storage key prefix is empty after sanitization")
        key = f"{prefix}/{logical_key}"
    else:
        key = logical_key
    if len(key.encode("utf-8")) > MAX_KEY:
        raise FilenameError("Storage key is too long")
    return StorageIdentity(filename=filename, key=key)
