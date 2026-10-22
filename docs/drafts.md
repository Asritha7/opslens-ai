# Private Markdown draft intake

This slice lets an authenticated user with an assigned role save a Markdown document and inspect an extraction proposal. It does not edit, approve, publish, or recommend the upload. All three existing roles may create their own private drafts; this is separate from authority over published documents.

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
- This slice has no delete/edit UI or automatic retention. A trusted database operator must handle cleanup when needed; it must not erase published evidence.
- No automatic approval, publishing, cross-user sharing, or paid service is added.

## Storage and authorization

Migration 002 adds `opslens.upload_drafts` with UUID ID, opaque owner key, filename, source content, extraction proposal, and creation time. Published revisions and their current ACLs are untouched. The owner key hashes the authentication mode plus subject; Google and demo identities use separate namespaces. Changing a person's role does not transfer their drafts to others with that role. Removing their assigned role blocks subsequent draft access.

`opslens_draft_writer` is a separate non-superuser login, with only SELECT and INSERT on this table. It cannot read/write published documents, update/delete drafts, or assume evidence-reader roles. Existing evidence-reader accounts remain read-only and cannot read drafts.

The backend sets a transaction-local owner context derived from authenticated identity. PostgreSQL RLS filters reads and checks inserts against that context. The API accepts no owner override and uses parameterized queries. Missing and another owner's draft both return 404. Source and metadata are rendered with textContent, never HTML.

The application server and operating-system/database operator remain trusted: a holder of the dedicated database credential can set its owner context directly. This is defense in depth for API isolation, not cryptographic isolation from the operator. Drafts share the local PostgreSQL volume and backup/trust boundaries; they are not separately encrypted by the app. Signing out clears visible drafts, but cannot retract already-returned content.

## API contract

All routes use the existing authentication dependency and require an assigned role. Google cookie-authenticated POSTs also require the configured Origin and `X-Runreviq-Request: 1`. An unassigned Google identity receives 403. Demo bearer mode remains available only when Google is not configured.

| Endpoint | Input / response |
|---|---|
| `POST /v1/drafts?filename=example.md` | Raw UTF-8 body with `Content-Type: text/markdown`; 201 with stored draft and proposal |
| `GET /v1/drafts` | `{drafts: [...]}` containing own IDs, filenames, creation times, and draft status, newest first |
| `GET /v1/drafts/{uuid}` | Own stored draft with content and proposal; missing/denied both 404 |

The detail response contains `id`, `filename`, `created_at`, `status: draft`, `content`, and `proposal`. The proposal retains the extraction contract: `review_required: true`, proposed fields, issues, provenance, and source fingerprint. ID/owner/status are assigned by the server, not extracted from text.

Upload bodies are streamed with a byte cap before extraction. Errors: 401 unauthenticated; 403 unassigned/failed Google CSRF check; 413 oversized; 415 wrong media type; 422 invalid filename, encoding, content, or UUID; 429 per-owner quota reached; 503 unavailable storage. Generic errors do not echo credentials or source text. Responses inherit the API's no-store and browser security headers.

## Setup

Add the private `DRAFTS_PASSWORD`, run the numbered migrations, and restart the API as described in [setup](../SETUP.md#private-markdown-drafts). Bootstrap preserves existing passwords and verifies applied migration checksums. Never put uploaded drafts or credentials into the public repository.
