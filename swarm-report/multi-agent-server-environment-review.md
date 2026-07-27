# Review report: Multi-agent server environment

## Verdict

Ship.

## Findings

No remaining code or configuration findings.

The review required three `/build` rework passes. They closed:

- authenticated release-manifest binding and schema-aware migration failure handling;
- post-start capacity/OOM gates and real SFTP chroots;
- explicit per-agent routing with no wildcard/default capture;
- approval-gated shared OpenClaw delivery with additive drift/deletion refusal and restore;
- arbitrary-agent secret loading through a protected Gateway environment;
- candidate-image Alembic head binding;
- a reviewable, fail-safe nftables artifact;
- protected transient OpenClaw validation and probes using the staged/live config path.

## Verification

```text
poetry run pytest -q
290 passed, 1 warning in 111.05s

poetry run ruff check app tools tests alembic
All checks passed!

poetry run mypy app tools tests
Success: no issues found in 84 source files

production Compose validation
pass

workflow/inventory/OpenClaw/migration metadata parse
4 YAML and 2 JSON files validated

poetry run alembic heads
b9b12bbd4cb0 (head)

git diff --check
clean
```

The pytest warning is the existing Windows `.pytest_cache` permission warning.

Final Git Bash/OpenClaw/nftables runtime validation was unavailable locally because the approval
service quota was exhausted. CI contains the Bash, actionlint, and pinned secretless OpenClaw
checks. Ubuntu bootstrap, firewall apply/reconnect, reboot, external LLM/Mattermost probes,
rollback/restore, scheduler ownership, and sibling preservation remain documented rollout gates,
not locally completed acceptance claims.
