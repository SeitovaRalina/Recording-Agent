---
name: commit
description: Create detailed local Git commits that follow Conventional Commits 1.0.0. Use when Codex must turn staged changes into a commit message, validate type/scope/breaking-change syntax, commit without pushing, or report commit contents and verification.
---

# Skill: /commit

ORCHESTRATOR. Generates and creates local Conventional Commits. Never pushes.

## Invocation

```text
/commit
/commit "feat(api): add recording endpoint"
```

## Workflow

1. Read `git status --short` and `git diff --cached`. Never include unrelated user changes.
2. If nothing is staged, stop and ask the user to stage intended files. Never stage broadly with `git add .`.
3. Classify change:
   - `feat`: new user-visible capability
   - `fix`: bug correction
   - `build`: build/dependency/tooling change
   - `chore`: maintenance without product behavior
   - `ci`: CI workflow
   - `docs`: documentation only
   - `refactor`: behavior-preserving restructuring
   - `test`: tests only
   - `perf`: performance improvement
   - `revert`: revert a prior commit
4. Choose a short noun scope when useful: `api`, `db`, `infra`, `migrations`, `tests`, `docs`, or repository-specific scope.
5. Draft header exactly:

   ```text
   <type>[optional(scope)][!]: <imperative description>
   ```

6. For non-trivial work, add a detailed body after one blank line. Explain what changed, why, compatibility or operational impact, and verification commands with real results.
7. Mark breaking changes with `!` in the header and/or a footer:

   ```text
   BREAKING CHANGE: describe migration impact and upgrade action
   ```

8. Show proposed message and staged-file summary before commit when the user did not provide an exact message.
9. Run `git commit` locally. Never run `git push`, `git reset --hard`, `git clean`, amend, or rebase as part of this skill.
10. Report commit hash, complete message, changed-file summary, and verification output.

## Rules

- Header type and description are mandatory; description starts after `: ` and is concise.
- Use lowercase type; keep scope a noun in parentheses.
- One logical change per commit. Split unrelated changes when possible.
- Do not claim tests passed unless command was actually run; quote real output.
- Preserve existing staged and unstaged work; never silently stage, discard, or rewrite it.
- Commit body may be multiline and detailed; Conventional Commits allows body and footers.
- Push requires a separate explicit user request and is outside this skill.

## Examples

```text
feat(backend): add automatic migration service

Run Alembic upgrade head in a one-shot Compose service before app startup.
Persist generated migrations through the project bind mount.

Verified: docker compose config; pytest -v (12 passed).
```

```text
fix(db)!: align status column types with migration metadata

BREAKING CHANGE: recreate development database before applying the revised baseline.
```

## Return

```yaml
status: complete | blocked
commit: <hash or null>
message: <full commit message or null>
changed_files: [<path>, ...]
verification: <real command output>
blocked_reason: <only if blocked>
```
