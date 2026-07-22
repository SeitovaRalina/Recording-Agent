from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_client() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "openclaw"
        / "skills"
        / "recording-agent"
        / "scripts"
        / "recording_agent.py"
    )
    spec = importlib.util.spec_from_file_location("recording_agent_skill_dm_client", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLIENT = _load_client()


def test_questions_use_trusted_dm_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_USER_ID", "trusted-user")
    monkeypatch.setenv("RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID", "trusted-dm")

    args = CLIENT._parser().parse_args(["questions", "--limit", "12"])

    assert args.recruiter_user_id == "trusted-user"
    assert args.mattermost_dm_channel_id == "trusted-dm"
    assert args.limit == 12


def test_questions_reject_conflicting_explicit_dm_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_USER_ID", "trusted-user")
    monkeypatch.setenv("RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID", "trusted-dm")

    with pytest.raises(CLIENT.ClientError, match="trusted DM channel"):
        CLIENT._parser().parse_args(
            [
                "questions",
                "--mattermost-dm-channel-id",
                "attacker-dm",
            ]
        )


def test_explicit_dm_metadata_remains_available_without_trusted_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RECORDING_AGENT_RECRUITER_USER_ID", raising=False)
    monkeypatch.delenv("RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID", raising=False)

    args = CLIENT._parser().parse_args(
        [
            "questions",
            "--recruiter-user-id",
            "local-user",
            "--mattermost-dm-channel-id",
            "local-dm",
        ]
    )

    assert args.recruiter_user_id == "local-user"
    assert args.mattermost_dm_channel_id == "local-dm"


def test_conflict_failure_does_not_print_backend_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "must-not-appear"
    monkeypatch.setenv("RECORDING_AGENT_BACKEND_SECRET", secret)
    monkeypatch.setenv("RECORDING_AGENT_RECRUITER_USER_ID", "trusted-user")
    monkeypatch.setattr(
        sys,
        "argv",
        ["recording_agent.py", "status", "--recruiter-user-id", "attacker-user"],
    )

    assert CLIENT.main() == 1
    output = capsys.readouterr().out
    assert secret not in output
    assert "attacker-user" not in output


def test_partial_answer_sends_only_validated_exact_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_id = "11111111-1111-1111-1111-111111111111"
    question_set_id = "22222222-2222-2222-2222-222222222222"
    captured: dict[str, object] = {}

    def request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        captured.update(method=method, path=path, **kwargs)
        return {"accepted": [], "rejected": [], "pending": [question_id]}

    monkeypatch.setattr(CLIENT, "_request", request)
    args = CLIENT._parser().parse_args(
        [
            "answer",
            "--recruiter-user-id",
            "trusted-user",
            "--mattermost-dm-channel-id",
            "trusted-dm",
            "--actions-json",
            json.dumps(
                [
                    {
                        "question_id": question_id,
                        "question_set_id": question_set_id,
                        "action": "resolve",
                        "capability": "one-time-capability",
                        "expected_version": 4,
                        "idempotency_key": "answer-0001",
                        "choice": 2,
                    }
                ]
            ),
        ]
    )

    CLIENT._execute(args)

    assert captured["method"] == "POST"
    assert captured["path"] == "/tools/questions/answer"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["recruiter_user_id"] == "trusted-user"
    assert body["mattermost_dm_channel_id"] == "trusted-dm"
    actions = body["actions"]
    assert isinstance(actions, list)
    assert actions[0]["choice"] == 2


@pytest.mark.parametrize(
    "actions",
    [
        [],
        [{"unexpected": "field"}],
        [
            {
                "question_id": "11111111-1111-1111-1111-111111111111",
                "question_set_id": "22222222-2222-2222-2222-222222222222",
                "action": "resolve",
                "capability": "token",
                "expected_version": 1,
                "idempotency_key": "answer-0001",
            }
        ],
    ],
)
def test_partial_answer_rejects_unbounded_or_ambiguous_actions(actions: object) -> None:
    with pytest.raises(CLIENT.ClientError):
        CLIENT._question_actions(json.dumps(actions))


def test_question_message_never_renders_capability() -> None:
    message = CLIENT._message_for(
        "questions",
        {
            "items": [
                {
                    "filename": "interview.webm",
                    "reason": "multiple_candidates",
                    "capability": "must-not-render",
                    "choices": [
                        {
                            "name": "Candidate",
                            "project_or_spot": "Backend",
                            "url": "https://notion.test/card",
                        }
                    ],
                }
            ]
        },
    )

    assert "interview.webm" in message
    assert "📍 Spots: Backend" in message
    assert "https://notion.test/card" in message
    assert "must-not-render" not in message


def test_cleanup_preview_message_requires_explicit_confirmation() -> None:
    message = CLIENT._message_for(
        "cleanup-preview",
        {
            "items": [
                {
                    "recording_id": "11111111-1111-1111-1111-111111111111",
                    "filename": "completed.webm",
                }
            ],
            "capability": "must-not-render",
        },
    )

    assert "Nothing has been moved" in message
    assert "Explicit confirmation is required" in message
    assert "must-not-render" not in message
