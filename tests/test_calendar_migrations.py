import importlib.util
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

MIGRATIONS = Path(__file__).parents[1] / "alembic" / "versions"


def load_revision(filename: str, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, MIGRATIONS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load migration {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calendar_migration_chain_is_linear_and_constraints_are_named() -> None:
    schema = load_revision(
        "2e68d69a2654_add_recruiter_calendar_selection.py", "calendar_schema_revision"
    )
    data = load_revision(
        "20260715_1400_backfill_legacy_calendar_defaults.py", "calendar_data_revision"
    )
    source = (MIGRATIONS / "2e68d69a2654_add_recruiter_calendar_selection.py").read_text()

    assert schema.down_revision == "20260714_1000"
    assert data.down_revision == schema.revision
    assert "fk_recruiter_calendar_recruiter_id_recruiter_config" in source
    assert "fk_recordings_matched_calendar_id_recruiter_calendar" in source
    assert "pk_recruiter_calendar" in source


def test_legacy_backfill_url_validation_and_id_are_deterministic() -> None:
    migration = load_revision(
        "20260715_1400_backfill_legacy_calendar_defaults.py", "calendar_data_helpers"
    )
    canonical = cast(Callable[[str], str | None], migration.canonical_legacy_url)
    make_id = cast(Callable[[uuid.UUID, str], uuid.UUID], migration.backfill_id)
    recruiter_id = uuid.UUID("cb1fa315-f273-4e74-95b0-76c90b3348ca")
    safe_url = "https://caldav.yandex.ru/calendars/recruiter/"

    assert canonical(" HTTPS://CALDAV.YANDEX.RU//calendars/recruiter/ ") == safe_url
    assert canonical("http://caldav.yandex.ru/calendar/") is None
    url_with_basic_auth = (
        "https://user:secret@caldav.yandex.ru/calendar/"  # pragma: allowlist secret
    )
    assert canonical(url_with_basic_auth) is None
    assert canonical("https://caldav.yandex.ru/calendar/#fragment") is None
    assert make_id(recruiter_id, safe_url) == make_id(recruiter_id, safe_url)
    assert make_id(uuid.uuid4(), safe_url) != make_id(recruiter_id, safe_url)
