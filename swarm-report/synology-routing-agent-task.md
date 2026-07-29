# Task: Synology Interview Destination Routing

## Problem

Recording Agent must store interview recordings in Synology under a bounded set of recruiter-owned
folders. The candidate card's `📍 Spots` relation can identify the vacancy/project/role, but it
does not reliably tell whether an engineering interview belongs to the external-project or
internal-interview tree.

This is especially ambiguous when both target trees contain the same role folder, for example
`Flutter`.

Folder selection is an OpenClaw/Mila LLM-assisted decision over a bounded Synology inventory.
Backend must not hardcode semantic mappings such as `Java -> Backend`, because recruiter meeting
titles and Spot names are not predictable enough for static rules. Backend also must not call an
LLM directly for this decision; OpenClaw/Mila performs the language reasoning and then calls a
narrow Backend intent.

## Allowed Roots

Backend may route interview recordings only under these roots:

- `/home/Recruiting-NE/2. Interviews`
- `/home/Recruiting-E/2. Interviews external`
- `/home/Recruiting-E/3. Interviews internal`

No other Synology folder may be selected automatically for interview recordings. Non-interview
work-meeting routing remains a separate manual destination flow.

## Routing Inputs

Backend may use these signals:

- matched candidate card title/name;
- matched calendar event title;
- exactly one resolved `📍 Spots` relation title;
- explicit recruiter answer from a pending manual-review question;
- current bounded Synology folder inventory exposed by Backend.

`📍 Spots` is not a direct destination field. It does not define the final folder or
`external` versus `internal`. It is only one text signal for finding candidate folders in the
allowed Synology inventory.

There will be no `Recording Root` or `Recording Folder` fields in Notion.

## Deterministic Rules

1. Backend discovers and persists only folders under the allowed roots as opaque
   `storage_destinations`.
2. OpenClaw/Mila receives bounded destination choices plus the text signals: resolved `📍 Spots`
   title, candidate card title, and calendar event title.
3. OpenClaw/Mila's LLM ranks candidate folders from that bounded list. Backend does not implement
   semantic alias rules or infer folder names itself.
4. If OpenClaw/Mila returns exactly one high-confidence destination ID, Backend validates that ID
   and may route automatically.
5. If OpenClaw/Mila returns zero or multiple plausible destination IDs, Mila asks the recruiter
   with a bounded list of matching folders.
6. If the recruiter says none of the folders fit, Mila asks for a new one-component folder name and
   the allowed parent root.
7. A recruiter may override any stored or inferred destination at any time before or after upload.
   Backend must treat this as an explicit bounded reroute request, validate the requested
   destination or newly requested child folder under the allowed roots, move/re-upload as needed,
   create or refresh the Synology share link, and update durable state idempotently.

## Manual Review Question

When `external/internal` is ambiguous, Mila asks a bounded question:

> This recording matches `<candidate>` / `<spot>`, and both external and internal folders are
> possible. Is this interview for an external project or for an internal role?

Choices:

- External project -> `/home/Recruiting-E/2. Interviews external/<role>`
- Internal role -> `/home/Recruiting-E/3. Interviews internal/<role>`
- Different folder -> show bounded allowed choices under the three allowed roots

Backend persists the selected `interview_scope` and destination ID before upload. Retries reuse the
same persisted destination and never ask again unless the stored destination becomes invalid.

## Automatic Unique Match

If OpenClaw/Mila returns exactly one suitable destination ID under the allowed roots, Backend may
route without asking after validation. Examples of decisions the LLM may make from inventory:

- `Aldo` exists only under `/home/Recruiting-E/2. Interviews external/Aldo`
- `Frontend` exists only under `/home/Recruiting-E/2. Interviews external/Frontend`
- `Java-разработчик @Т-банк` may be interpreted by OpenClaw/Mila as fitting
  `/home/Recruiting-E/2. Interviews external/Backend` when no competing suitable folder exists

The Java-to-Backend reasoning happens in OpenClaw/Mila over the bounded list, not in Backend code
or a Backend alias table.
The automatic route must still use a persisted destination ID and pass the same root containment,
permission, symlink, and collision checks as manual choices.

## Ambiguous Match

If multiple plausible folders are found, Mila asks the recruiter to choose from a bounded list.
Example:

`Flutter` can match both:

- `/home/Recruiting-E/2. Interviews external/Flutter`
- `/home/Recruiting-E/3. Interviews internal/Flutter`

Mila asks whether the recording belongs to the external project or internal role folder. The
recruiter may also choose a different listed folder or ask to create a new folder.

## No Match

If no plausible folder is found, Mila does not invent one silently. It asks the recruiter:

- choose an existing folder under the allowed roots; or
- provide a new one-component folder name and the allowed parent root where it should be created.

Backend validates and creates the new folder before upload.

## Recruiter Override

A recruiter can ask Mila to move a recording to another existing folder or to create a new folder
under one of the allowed roots.

Requirements:

- Mila may present folder choices and parse the request, but Backend resolves the final destination.
- Free-form folder names are accepted only as one safe path component at a validated parent.
- New folders may be created only under the three allowed roots.
- Overrides are audited and persisted before any storage mutation.
- If the recording already has a Synology file/link, Backend must avoid duplicate orphan files:
  either move the existing Synology file when a safe move operation is implemented, or upload a new
  copy and mark the previous path as superseded for operator cleanup. Automatic deletion of the old
  file is forbidden without an explicit cleanup approval.

## Fail-Closed Cases

Manual review is required when:

- `📍 Spots` is empty and no safe folder can be inferred;
- multiple `📍 Spots` are related and no prior recruiter selection exists;
- both external and internal contain the same inferred subfolder and `interview_scope` is absent;
- candidate/calendar/spot signals map to conflicting folders;
- OpenClaw/Mila folder selection produces zero or multiple suitable candidates;
- OpenClaw/Mila returns a destination ID that Backend cannot validate;
- target folder is missing, inaccessible, outside the allowed roots, or a symlink/unsafe path;
- storage key collision is detected.

## Acceptance Criteria

- The agent never treats `📍 Spots` as a direct destination or as `external/internal` truth.
- Ambiguous external/internal matches produce a recruiter question.
- Unique OpenClaw/Mila-selected destination IDs under exactly one allowed root are routed
  automatically after Backend validation.
- Backend contains no semantic hardcoded mappings such as `Java -> Backend`.
- `Java-разработчик @Т-банк` can be matched by OpenClaw/Mila's LLM to `Backend` when that is the
  only suitable destination in the bounded inventory.
- The question offers only bounded, canonical Synology destinations.
- Recruiter override can choose another existing allowed destination or request a new validated
  child folder.
- The selected destination is persisted before transfer.
- Upload creates a Synology share link and writes it through the existing state machine.
- Tests cover duplicate role folders such as `Flutter` in both external and internal roots.
