---
type: reference
status: current
last_updated: 2026-09-30
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
4. Validate the recruiter's resolved property map against the retrieved data-source schema:
   - `name_prop` must have type `title`.
   - `date_prop` must have type `date`.
   - `recording_prop` must have type `files`.
   - `project_prop`, when set, must have type `relation` and `project_prop_type` must be
     `relation`.
   - Contacts depend on `contacts_mode`: `none` checks nothing; `formula` requires
     `contacts_prop` of type `formula`; `relation` requires `contacts_relation_prop` of type
     `relation`.
5. Select the source only when exactly one schema is compatible.

Zero compatible sources is a schema error. More than one compatible source is an ambiguity error.
Source ordering must never choose a winner. Successful resolution may be cached in process by the
database ID and every configured property name, project type, and contacts mode, but the cache
must be bounded.

## Per-recruiter property map

Property names are resolved per recruiter by `resolve_notion_property_map`
(`app/services/recruiter_schema.py`). `recruiter_config.notion_property_map` may override any
subset of keys; every missing key falls back to the global `NOTION_*_PROP` settings, and a NULL
column means the global map. The same resolved map drives candidate search, reassignment,
page updates, the operator preflight, and the preflight schema hash.

## Candidate contacts

Contacts are only a supplementary matching signal; they never block a match.

- `none` — the database has no contacts field; pages carry no emails.
- `formula` — `contacts_prop` is a formula rendering a string; emails are extracted from it.
- `relation` — the interview page links to a candidate card through `contacts_relation_prop`.
  With exactly one link, the backend retrieves that page (`GET /v1/pages/{page_id}`) and extracts
  emails from its `contacts_target_prop` rich_text value, caching per linked page within one
  query. Zero links, several links, a malformed relation, or a missing / non-rich_text target
  property yield no emails. The operator preflight does not check the target property on the
  linked database; a mismatch soft-fails at runtime to no emails.

All modes use the same email extraction: valid addresses only, lowercased, deduplicated.

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

## Recording file-link update

Page updates remain page-scoped:

```http
PATCH /v1/pages/{page_id}
```

```json
{
  "properties": {
    "General Interview recording": {
      "files": [
        {
          "name": "interview-recording.webm",
          "external": {
            "url": "https://storage.example/recording"
          }
        }
      ]
    }
  }
}
```

Send `Notion-Version: 2026-03-11`. The recording property must already exist as type `files` in the
selected data-source schema. The external file `name` is the original recording filename. Updating
a `files` property replaces its entire array; this integration intentionally owns the dedicated
recording property and writes one external Synology share link.

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
   `title`, `date`, and `files` properties under the configured names.
6. Record sanitized pass/fail evidence. Do not query candidate pages and do not patch any page.
7. Repeat the read-only discovery against the production database ID after explicit sharing.

Production enablement is blocked for that recruiter when sharing fails, no compatible schema
exists, or multiple schemas are compatible. Never resolve ambiguity by response order.

## Project topology

- One `NOTION_TOKEN` serves the shared workspace.
- Each recruiter supplies an original database ID through configuration.
- Each recruiter may supply its own property map; otherwise the global defaults apply.
- Runtime discovery supplies data-source IDs; they are neither configured nor persisted.
- Known global property defaults are `Name`, `General Interview Date`,
  `General Interview recording`, `📍 Spots` (relation), and `TBD` (formula contacts).
