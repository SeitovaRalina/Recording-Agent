# Review: multi-tenancy

Diff `7d5db01..a2e8097` (swarm-report excluded). Verdict: **ship**. `acceptance_unmet: []`.

## Findings

- MEDIUM, `app/tools/notion.py:932` (`_retrieve_related_property`, via `_with_relation_contacts`
  :965): in `contacts_mode=relation`, a linked Candidates card that is unshared, deleted or
  trashed returns 403/404, and the error aborts `find_and_match` for the whole recording. This
  breaks the rule that email is only a supplementary signal. Fix: map non-transient 403/404 to
  `emails=()`, let transient/5xx/auth errors propagate, add respx tests.
- MEDIUM, `app/services/notion_reassignment.py:132`: test gap. The new cross-recruiter guard
  (409) and the confirm route's `_bound_recruiter` (404/403) have no tests. The logic checks out:
  capability and one-time-token checks are unchanged, and access only gets tighter. Fix: a test
  for another recruiter's recording → 409 with no Notion calls, and one for an inactive binding →
  404.
- LOW, `app/services/canary.py:162`: the legacy hash payload is byte-identical only while the
  global `NOTION_PROJECT_PROP_TYPE=relation` (true today). Fix: assert it in the legacy-hash test.
- LOW, `app/services/recruiter_schema.py:108-110`: a non-list `synology_interview_roots` value
  splits into characters and surfaces as a 500. The CLI validates on write. Fix: reject non-list
  values and map the error to `DestinationRejectedError`.

## Focus areas

1. NULL rows (Anton): OK. Settings fallback works field by field, and the legacy hash payload is
   reproduced.
2. Cross-tenant roots: OK. No constructor-time roots remain, and every path passes the
   recruiter's roots.
3. Relation contacts: I/O is bounded and cached. Zero, several or malformed links give `()`.
   The only gap is the first MEDIUM finding.
4. Confirm endpoint: access is tighter, not looser.
5. Migration: reversible, the head matches `deploy/release-metadata.json`.

Not covered by tests: the confirm 409/404 path, relation 403/404, and migration upgrade/downgrade
(not applied locally).
