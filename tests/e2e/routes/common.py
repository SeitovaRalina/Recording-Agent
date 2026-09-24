"""Shared test data of the prod stand (Notion spot pages, Synology roots)."""

from __future__ import annotations

from typing import Any

SPOTS = {
    "python": "397c8889-e4c8-81d7-8bcb-f77c42da96e8",  # Python-разработчик @Т-банк
    "java": "397c8889-e4c8-8118-ac1b-e5efbe7f83f2",  # Java-разработчик @Т-банк
    "analyst": "397c8889-e4c8-81fc-af7a-f7477fecf6a9",  # Бизнес-аналитик @Т-банк
    "discovery": "397c8889-e4c8-8142-beea-ccafcc8c479f",  # Discovery @Дизайн машина
}

EXTERNAL = "/home/Recruiting-E/2. Interviews external"
INTERNAL = "/home/Recruiting-E/3. Interviews internal"
NON_ENGINEERING = "/home/Recruiting-NE/2. Interviews"

SCAN = "Проверь новые записи"


def terminal_sent(state: dict[str, Any], count: int) -> bool:
    """At least `count` terminal (completion/error) DMs of this route were delivered."""
    sent = [
        o
        for o in state["outbox"]
        if o["status"] == "sent" and str(o["dedupe_key"]).startswith("terminal:")
    ]
    return len(sent) >= count
