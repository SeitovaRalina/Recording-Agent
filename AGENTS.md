# Recording Agent — Working Agreement

Dev-loop: `/plan → /build → /review → /debug`

## What this project is

OpenClaw agent that automates interview recording processing:
**Яндекс.Диск** → match calendar event + Notion candidate card → upload **Synology** → update **Notion** → notify recruiter via **Mattermost**.

Read `.memory-bank/index.md` before anything else. Follow links to detail files.
Missing or contradictory memory → say so, do not invent project facts.

## The loop

1. `/plan "<feature>"` — planner + skeptic design the feature. Output: `swarm-report/<slug>-plan.md` with acceptance criteria.
2. `/build <slug>` — exec agents implement the approved plan, run tests. Multi-layer → parallel exec agents.
3. `/review <slug>` — reviewer checks diff vs plan. Verdict: `ship` or `rework`.
4. `/debug "<error>"` — reproduce → ladder hypotheses → root cause → minimal fix.

Test-gate hook blocks "done" until `pytest` runs and output is cited.

## Agents

### Consilium (design, review, debug — never bulk-edit)
| Role | Agent | Skill |
|------|-------|-------|
| planner | `.claude/agents/planner.md` | `/plan` |
| skeptic | `.claude/agents/skeptic.md` | `/plan` |
| reviewer | `.claude/agents/reviewer.md` | `/review` |
| debugger | `.claude/agents/debugger.md` | `/debug` |

### Utility skills (no agent — run in main loop)
| Skill | Purpose |
|-------|---------|
| `/migrate` | Alembic migrations: `generate "<msg>"`, `upgrade`, `downgrade`, `history`, `check` |
| `/seed` | Load/clean/status dev fixture data. Never runs against production DATABASE_URL. |

### Executing (write code — matched by file scope)
Match order: specific first, fallback last.

| Agent | Scope |
|-------|-------|
| `python-fastapi.md` | `**/*.py`, `pyproject.toml` — backend tools service |
| `terraform-yandex.md` | `**/*.tf`, `.terraform.lock.hcl` — Yandex Cloud infra |
| `devops.md` | `Dockerfile`, `docker-compose*`, `.github/**`, `Makefile` |
| `backend.md` | fallback for anything not matched above |

No frontend, mobile, react, flutter, ios, android agents — this project has none of those.
No scope match → ask which exec agent owns the change.

## Working agreement

- **Read memory bank first.** `.memory-bank/index.md` is the table of contents. Follow links.
- **Resolve open questions before coding.** Check `.memory-bank/open-questions.md`. If a blocker is unresolved → surface it, don't guess.
- **Accuracy > speed.** Verify before claiming done. Tests pass ≠ feature works. Check end-to-end.
- **Disagree loudly.** Plan wrong, scope bloated, approach flawed → say it and give one alternative. Do not play along.
- **Stay in scope.** python-fastapi touches only Python files. terraform-yandex touches only `.tf`. Cross-layer impact → note in return for sibling agent, do not reach across.
- **Edit > Write.** Modify existing files; new files only when plan requires.
- **No secrets in code.** OAuth tokens, API keys, passwords → pydantic-settings + env/Lockbox only. `SecretStr` for sensitive fields. Never in logs.
- **No hardcoded recruiter data.** Database IDs, Mattermost channel IDs, Synology paths → config/env, never literals in code.
- **Ask before destructive ops.** Especially: Яндекс.Диск delete, Synology file deletion, Notion card edits. These are irreversible.
- **Terse output.** Drop filler, keep every technical fact. Code, commits, PRs: written normally.
- **English only in docs and memory.** All `.md` files in `docs/` and `.memory-bank/` must be written in English. Product names (Яндекс.Диск, Notion, etc.) and API paths/folder names that contain Cyrillic are exempt — they are proper nouns or literal strings, not prose.

## Exec-agent details

`/build` maps plan tasks' affected files to exec agents. Run `pyproject.toml` to confirm Python version and deps before implementing.

Stack defaults (2026, override if repo says otherwise):
- Python 3.13 · FastAPI 0.136 · Pydantic v2 · SQLAlchemy 2.0 async · asyncpg · Alembic · uv · httpx · pytest + anyio
- No sync DB calls, no blocking I/O in async path
- Separate ORM models from Pydantic schemas
- Config via `pydantic-settings BaseSettings`, `@lru_cache`
