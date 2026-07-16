---
type: reference
status: current
last_updated: 2026-07-16
sources:
  - https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03
  - https://developers.notion.com/reference/retrieve-a-database
  - https://developers.notion.com/reference/retrieve-a-data-source
  - https://developers.notion.com/reference/query-a-data-source
  - https://developers.notion.com/reference/update-page
  - https://developers.notion.com/reference/errors
---

# Notion API

## Contract

Base URL: `https://api.notion.com/v1`.

Every request sends:

```http
Authorization: Bearer <NOTION_TOKEN>
Notion-Version: 2026-03-11
Content-Type: application/json
```

The token is an Internal Integration token. Store it as a `SecretStr`; unwrap it only at the HTTP
boundary. Never log the token or raw error payloads that may contain customer data.

Persist only each recruiter's original database ID in `recruiter_config.notion_database_id` and
`recording.notion_database_id`. A database ID is not a data-source ID.

## Database-to-data-source resolution

Candidate lookup resolves a queryable data source at runtime:

1. `GET /v1/databases/{database_id}`.
2. Parse the returned `data_sources` descriptors.
3. For every descriptor, call `GET /v1/data_sources/{data_source_id}`.
4. Validate configured properties against the retrieved data-source schema:
   - `notion_name_prop` must have type `title`.
   - `notion_date_prop` must have type `date`.
   - `notion_recording_prop` must have type `url`.
5. Select the source only when exactly one schema is compatible.

Zero compatible sources is a schema error. More than one compatible source is an ambiguity error.
Source ordering must never choose a winner. Successful resolution may be cached in process by the
database ID and all three configured property names, but the cache must be bounded.

When a cached source query returns source-not-found, invalidate the cache entry, rediscover, and
retry the query exactly once. Do not retry authentication, sharing, schema, ambiguity, or arbitrary
API failures without bound.

## Candidate query

Query the selected data source, never the database:

```http
POST /v1/data_sources/{data_source_id}/query
```

```json
{
  "filter": {
    "and": [
      {
        "property": "Name",
        "title": {"contains": "Ivan Petrov"}
      },
      {
        "property": "General Interview Date",
        "date": {"equals": "2026-07-16"}
      }
    ]
  },
  "page_size": 10
}
```

The date is the calendar event date in the recruiter's configured local timezone. Parse at most ten
pages into typed values containing page ID, page URL, title, and date. Existing semantics remain:
zero results require manual review, one result matches, and multiple results require manual review.

`POST /v1/databases/{database_id}/query` and `Notion-Version: 2022-06-28` are legacy contracts and
must not be used by runtime code.

## Recording URL update

Page updates remain page-scoped:

```http
PATCH /v1/pages/{page_id}
```

```json
{
  "properties": {
    "General Interview recording": {
      "url": "https://storage.example/recording"
    }
  }
}
```

Send `Notion-Version: 2026-03-11`. The recording property must already exist as type `url` in the
selected data-source schema.

## Sharing and errors

Connect the Internal Integration directly to each original recruiter database. Sharing only a
parent page, a copied linked view, or an embedded view does not grant reliable access to the
original database and its data sources.

Handle failures with typed, sanitized errors:

| Condition | Meaning | Operator action |
|---|---|---|
| `401` | Invalid or revoked token | Replace `NOTION_TOKEN` |
| `403` | Resource forbidden or not shared | Connect the integration to the original database |
| Database `404` | Database unavailable, wrong ID, or unshared | Verify original database ID and sharing |
| Data source `404` | Source unavailable or cached ID stale | Rediscover once when the ID came from cache |
| Schema mismatch | Required property missing or wrong type | Correct configured names or copied schema |
| Source ambiguity | Multiple sources match the schema | Make schemas uniquely identifiable before enablement |
| `400`, `429`, `5xx` | Validation, rate, or service failure | Surface sanitized query/update failure; follow retry policy |
| Malformed JSON shape | Contract violation or unexpected payload | Fail closed and alert operator |

Do not include tokens, authorization headers, or raw response bodies in errors or logs.

## Read-only rollout probe

Run this process before production enablement for every recruiter:

1. Copy the recruiter's database into a test location without production candidate data or writes.
2. Connect the Recording Agent integration to the copied database.
3. Configure the probe with the copied database's original database ID and expected property names.
4. Send only `GET /v1/databases/{database_id}` and `GET /v1/data_sources/{data_source_id}` requests
   using `Notion-Version: 2026-03-11`.
5. Confirm the database payload exposes data sources and exactly one retrieved schema has
   `title`, `date`, and `url` properties under the configured names.
6. Record sanitized pass/fail evidence. Do not query candidate pages and do not patch any page.
7. Repeat the read-only discovery against the production database ID after explicit sharing.

Production enablement is blocked for that recruiter when sharing fails, no compatible schema
exists, or multiple schemas are compatible. Never resolve ambiguity by response order.

## Project topology

- One `NOTION_TOKEN` serves the shared workspace.
- Each recruiter supplies an original database ID through configuration.
- Runtime discovery supplies data-source IDs; they are neither configured nor persisted.
- Known property defaults are `Name`, `General Interview Date`, and
  `General Interview recording`.
