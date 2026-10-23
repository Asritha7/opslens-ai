# Private Markdown draft intake

This slice lets an authenticated user with an assigned role save a Markdown document and inspect an extraction proposal. Users can save metadata corrections as private review progress. It does not approve, publish, or recommend the upload. All three existing roles may create their own private drafts; this is separate from authority over published documents.

## User flow

1. Sign in and select a `.md` file under **Add a document for review**.
2. Select **Save draft and preview**. The server saves the source and extraction result in one transaction.
3. Inspect proposed fields, review issues, source quotations with line numbers, and the stored Markdown. Even a complete extraction remains review-required.
4. Select **Load my drafts** to reopen an earlier upload. Drafts survive API restarts and persist in the existing database volume.

The extractor supports the explicit Applicability section in [the template](runbook-template.md). It does not infer arbitrary prose, parse PDFs, or generate claims/citations. Uploaded authority fields cannot grant roles, approval, or verification. A draft never appears in the selector: that code continues to read only published document revisions.

## Validation and limits

- UTF-8 Markdown; at most 1,000,000 bytes per file. Empty, whitespace-only, and NUL-containing documents are rejected.
- Simple display filenames ending in `.md` (case-insensitive), up to 120 characters. Start with an ASCII letter/digit; remaining characters may include ASCII letters, digits, spaces, dots, underscores, and hyphens. Paths are rejected, and filenames are never used to open server files.
- At most 20 drafts per identity. Each successful upload creates a new draft, including repeat uploads. Quota enforcement is serialized per owner in the database.
- This slice has no delete UI or automatic retention. Metadata editing is supported, but source Markdown is immutable. A trusted database operator must handle cleanup when needed; it must not erase published evidence.
- No automatic approval, publishing, cross-user sharing, or paid service is added.

## Storage and authorization

Migration 002 adds `opslens.upload_drafts` with UUID ID, opaque owner key, filename, source content, extraction proposal, and creation time. Published revisions and their current ACLs are untouched. The owner key hashes the authentication mode plus subject; Google and demo identities use separate namespaces. Changing a person's role does not transfer their drafts to others with that role. Removing their assigned role blocks subsequent draft access.

`opslens_draft_writer` is a separate non-superuser login, with only SELECT and INSERT on the draft and review tables. It cannot read/write published documents, update/delete drafts, or assume evidence-reader roles. Existing evidence-reader accounts remain read-only and cannot read drafts.

The backend sets a transaction-local owner context derived from authenticated identity. PostgreSQL RLS filters reads and checks inserts against that context. The API accepts no owner override and uses parameterized queries. Missing and another owner's draft both return 404. Source and metadata are rendered with textContent, never HTML.

The application server and operating-system/database operator remain trusted: a holder of the dedicated database credential can set its owner context directly. This is defense in depth for API isolation, not cryptographic isolation from the operator. Drafts share the local PostgreSQL volume and backup/trust boundaries; they are not separately encrypted by the app. Signing out clears visible drafts, but cannot retract already-returned content.

## API contract

All routes use the existing authentication dependency and require an assigned role. Google cookie-authenticated POSTs also require the configured Origin and `X-Runreviq-Request: 1`. An unassigned Google identity receives 403. Demo bearer mode remains available only when Google is not configured.

| Endpoint | Input / response |
|---|---|
| `POST /v1/drafts?filename=example.md` | Raw UTF-8 body with `Content-Type: text/markdown`; 201 with stored draft and proposal |
| `GET /v1/drafts` | `{drafts: [...]}` containing own IDs, filenames, creation times, and draft status, newest first |
| `GET /v1/drafts/{uuid}` | Own stored draft with content and proposal; missing/denied both 404 |

The detail response includes `review` (null before the first save, otherwise the latest review), plus `id`, `filename`, `created_at`, `status: draft`, `content`, and `proposal`. The proposal retains the extraction contract: `review_required: true`, proposed fields, issues, provenance, and source fingerprint. ID/owner/status are assigned by the server, not extracted from text.

Upload bodies are streamed with a byte cap before extraction. Errors: 401 unauthenticated; 403 unassigned/failed Google CSRF check; 413 oversized; 415 wrong media type; 422 invalid filename, encoding, content, or UUID; 429 per-owner quota reached; 503 unavailable storage. Generic errors do not echo credentials or source text. Responses inherit the API's no-store and browser security headers.

## Setup

Add the private `DRAFTS_PASSWORD`, run the numbered migrations, and restart the API as described in [setup](../SETUP.md#private-markdown-drafts). Bootstrap preserves existing passwords and verifies applied migration checksums. Never put uploaded drafts or credentials into the public repository.

## Edit and save review progress

Open a draft, inspect **Original extraction** and its source lines, then edit the six fields under **Your metadata edits**. Save with **Save review progress**. The original Markdown and extraction never change. **Load my drafts** reopens the latest saved values. Editing source text, approving, publishing, or assigning authority is not supported.

All six fields are strings: title, service, environment, version_min, version_max_exclusive, key_rotation_enabled. Blank means missing; key rotation `none` explicitly means no requirement. Environment accepts production/staging, versions use X.Y.Z with an exclusive upper bound greater than the lower bound, and service uses an explicit identifier. Inputs are at most 200 characters each, with tighter semantic rules inherited from extraction. Unknown fields and non-string values are rejected. Permissions, verification, and approval fields cannot be submitted.

Incomplete or semantically invalid edits can be saved. The response shows field issues and separately includes only valid parsed values; invalid version ranges are excluded. Passing format checks does not establish accuracy or approval. Every save stays `in_progress`, `review_required: true`, and excluded from selection.

`POST /v1/drafts/{uuid}/review` accepts JSON `{expected_revision: 0, metadata: {...six string fields...}}`. Start with revision zero for an unedited draft; otherwise send the latest review revision. It returns `revision`, `created_at`, `metadata`, `validated_metadata`, `issues`, `status`, and `review_required`. It uses the same assigned identity and Google CSRF checks as uploads. Missing/inaccessible drafts return 404, stale versions return 409, invalid structures return 422, and storage failures return 503. The browser retains unsaved fields after failed saves; on conflict, copy changes before loading the latest draft.

Migration 003 adds append-only `opslens.draft_reviews` snapshots. A transaction lock serializes saves per draft, and revision checking prevents silent overwrites. RLS derives ownership through the parent draft; no UPDATE/DELETE grant is added. A draft has at most 100 saved review revisions. Earlier snapshots remain stored, but this UI displays only the latest. This is review progress, not a complete audit or approval system. The trusted application/database-operator boundary still applies.

Existing installations run `.venv/bin/python -m runreviq.database bootstrap`, then restart the API. No new password is required, and previously saved drafts remain accessible with `review: null` until first edited.
