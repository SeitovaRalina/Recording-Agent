# Plan: Migrate Notion integration to API version 2026-03-11   (slug: notion-2026-api)

## TL;DR

Replace the legacy `2022-06-28` database-query flow with Notion's current
`2026-03-11` data-source API. Keep each recruiter's existing original database ID as the only
persisted setting. At runtime, discover the database's data sources, validate their schemas, and
select exactly one compatible source before querying it. Fail closed on missing or ambiguous
schemas. No database migration is required.

Official migration references:

- `https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03`
- `https://developers.notion.com/reference/query-a-data-source`
- `https://developers.notion.com/reference/changes-by-version`

## Acceptance criteria

1. Every Notion request sends `Notion-Version: 2026-03-11`; runtime code contains no legacy
   `2022-06-28` request header.
2. `NotionClient.search_pages()` keeps accepting the original recruiter database ID. It calls
   `GET /v1/databases/{database_id}`, reads `data_sources`, and never treats a database ID as a
   data-source ID.
3. For every discovered source, the client calls `GET /v1/data_sources/{data_source_id}` and
   validates the configured name, date, and recording properties as `title`, `date`, and `url`.
4. Exactly one compatible source is selected. Zero compatible sources raises a typed schema
   error. More than one compatible source raises a typed ambiguity error. Source order never
   selects a winner.
5. Candidate lookup calls `POST /v1/data_sources/{data_source_id}/query` with the existing title
   contains filter, local-date equals filter, and page-size bound of 10. `NotionPage` parsing and
   the zero/one/many candidate semantics remain unchanged.
6. `PATCH /v1/pages/{page_id}` remains the recording-URL update endpoint and uses the current
   version header and URL-property body.
7. Successful database-to-source resolution is cached in process by database ID plus configured
   property names. Cache size is bounded. Concurrent first lookups for the same key do not perform
   duplicate discovery chains.
8. A cached query returning source-not-found invalidates the entry, rediscovers, and retries the
   query exactly once. Auth, schema, ambiguity, and other API failures are not retried without
   bound.
9. Typed, sanitized errors distinguish authentication, forbidden/unshared resources, unavailable
   database, unavailable/stale data source, schema mismatch, ambiguity, malformed payload, query
   failure, and update failure. Tokens and raw credential-bearing payloads are never exposed.
10. `RecruiterConfig.notion_database_id` and `Recording.notion_database_id` remain original
    database IDs. No ORM model or Alembic migration changes.
11. Candidate matching, scheduler statuses, upload/share ordering, and source-processing behavior
    remain unchanged.
12. Authoritative Notion documentation uses `2026-03-11`, `/v1/data_sources`, runtime discovery,
    unique schema selection, and current sharing guidance. Historical gate results are not
    rewritten.
13. A documented read-only pre-deploy probe retrieves and validates every active recruiter
    database against a copied test database first. Production enablement is blocked per recruiter
    on sharing, schema, or ambiguity failure.
14. Ruff lint, Ruff format check, strict mypy, and full pytest pass.

## Plan

### 1. Update the Notion client

Affected file: `app/tools/notion.py`.

- Add `NOTION_API_VERSION = "2026-03-11"` and use it for discovery, schema retrieval, query, and
  page update requests.
- Add typed models/parsers for database data-source descriptors and retrieved source schemas.
- Add typed errors for auth, forbidden access, database/source absence, malformed responses,
  incompatible schema, and source ambiguity.
- Preserve sanitized messages; do not include tokens or raw Notion response bodies.

### 2. Add runtime discovery and fail-closed selection

- Discover sources with `GET /v1/databases/{database_id}`.
- Retrieve each schema with `GET /v1/data_sources/{data_source_id}`.
- Match configured property names and exact types: name=`title`, date=`date`, recording=`url`.
- Select only when exactly one source is compatible.
- Keep the original database ID at all service and persistence boundaries.

### 3. Add bounded cache and stale-source recovery

- Cache the validated source ID by database ID and configured property names.
- Bound the cache and per-key concurrency state; no permanent/unbounded process cache.
- On a cached query 404, evict, rediscover, and retry once.
- Do not retry authentication, forbidden, schema, ambiguity, or arbitrary API errors.

### 4. Switch the query endpoint

- Query `POST /v1/data_sources/{data_source_id}/query`.
- Preserve title/date filters, result bound, page parsing, and update-page behavior.

### 5. Expand tests

Affected files:

- `tests/test_notion.py`
- `tests/test_candidate.py`
- `tests/test_scheduler.py`

Required tests:

- Single-source discovery, schema validation, and current query request chain.
- Multiple sources with exactly one compatible schema, zero compatible schemas, and multiple
  compatible schemas; verify source order is irrelevant.
- Missing/wrong name, date, or recording property types.
- Current header on database discovery, source retrieval, query, and page PATCH.
- 401, 403, database 404, source 404, 400 validation, 429, 5xx, malformed JSON shapes, and
  sanitized error messages.
- Cache hit, concurrent first lookup, bounded eviction, cached stale-source invalidation, and one
  retry only.
- Candidate service continues passing the recruiter database ID and configured local date.
- Scheduler candidate failure and happy path retain existing statuses and persist the original
  database ID.

### 6. Update authoritative documentation

Affected files:

- `docs/api-contracts/notion.md`
- `.memory-bank/auth-flow.md`
- `.memory-bank/open-questions.md`
- `swarm-report/phase-3-transfer-plan.md`
- `swarm-report/phase-3-transfer-build.md`

Use English prose in `docs/` and `.memory-bank/`. Correct legacy endpoint/header assumptions,
record that schema/property IDs come from data-source retrieval, document unique-source selection,
and add a copied-database read-only rollout probe. Preserve old test evidence as historical and add
new verification separately.

### 7. Gate

Run and quote real output:

```text
poetry run ruff check app tests alembic
poetry run ruff format --check app tests alembic
poetry run mypy app tests
poetry run pytest
```

## Blockers

None for implementation.

- Q5 remains an operational input: every recruiter must provide an original database ID and share
  it with the integration. Runtime discovery removes the need to preconfigure a data-source ID.
- Q8 remains a rollout constraint: a recruiter whose schema does not uniquely match the configured
  property names/types fails closed and is not enabled until corrected.

## Out of scope

- Persisting or manually configuring data-source IDs.
- ORM or Alembic migration changes.
- Migrating configured property names to Notion property IDs.
- Global retry/backoff redesign for Notion 429/5xx responses.
- Mattermost, OpenClaw, Yandex, Synology, retention, or matching algorithm changes.
- Production Notion writes or destructive database operations.

## Assumptions

- `2026-03-11` is the required fixed current API version, not a user-selectable arbitrary version.
- Existing recruiter values identify original databases shared directly with the integration.
- Schema compatibility is defined by the configured name/date/recording properties and their exact
  `title`/`date`/`url` types.
- Runtime discovery plus bounded caching is preferable to a persisted source ID that can become
  stale after source replacement.
- The current dirty Phase 3 worktree belongs to the user and must be preserved.
