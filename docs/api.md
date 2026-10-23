# Local API contract

Start the server using [SETUP.md](../SETUP.md). Base address: `http://127.0.0.1:8000`. The supplied server command binds only to loopback. Generated API documentation/OpenAPI endpoints and CORS access are disabled. Optional [Google OIDC login](google-login.md) uses local server-side sessions; production deployment, TLS, rate limiting, and automatic demo-key expiry remain unimplemented.

## Endpoints and authentication

Google mode uses an HttpOnly session cookie and disables bearer keys. Cookie-authenticated POSTs require `Origin: http://127.0.0.1:8000` and `X-Runreviq-Request: 1`. See [the authentication endpoint contract](google-login.md#endpoint-contract).

| Endpoint | Credential | Response |
|---|---|---|
| `GET /health` | None | `{"status":"ok"}`; process liveness only |
| `GET /v1/me` | Bearer key or Google session | `subject` and assigned `role` |
| `POST /v1/select` | Bearer key or Google session | Selection result below |
| `GET /v1/documents/{document_id}/revisions/{revision}` | Bearer key or Google session | Stored document revision under current access policy |

In demo mode, protected requests use `Authorization: Bearer <local-key>`. Use the supplied `runreviq.client` command to avoid putting keys into shell history. The private key file is plaintext with owner-only permissions and is Git-ignored. Records map a unique subject and token to platform, security, or intern. The server reloads it per request; revocation applies to subsequent authentication, not already-running requests.

## Selection request

```json
{
  "service": "identity-service",
  "software_version": "2.4.0",
  "environment": "production",
  "key_rotation_enabled": true
}
```

`service` is a 1–100 character identifier containing ASCII letters, digits, `_`, or `-`. `software_version` is an exact three-part numeric string, maximum 32 characters. `environment` is `production` or `staging`. The first three fields are required. `key_rotation_enabled` is a strict boolean or null, defaults to null, and means unknown when omitted/null. Extra fields, including `role`, are rejected. The supplied context is not checked against live infrastructure.

## Selection response

All four domain outcomes return HTTP 200. A conflict is a completed evaluation, not an HTTP server error.

| Status | Meaning |
|---|---|
| `selected` | Applicable verified guidance is available without detected conflict or uncertainty |
| `conflict` | Applicable documents contain opposing normalized rules |
| `needs_context_or_review` | Relevant documents require more user context or metadata review |
| `insufficient_evidence` | Suitable approved guidance accessible to the caller was not found |

| Field | Shape and meaning |
|---|---|
| `message` | Human-readable result summary |
| `next_steps` | List of suggested actions; the system executes none |
| `questions` | Objects with `field`, `question`, and `allowed_answers`; currently key rotation with true/false answers |
| `review_items` | Document ID, title, revision, path, and `reasons` |
| `conflict_details` | Action, `basis: catalog_rules`, explanation, and opposing document references/rules |
| `applicable_documents` | IDs of matching verified documents |
| `uncertain_documents` | IDs of otherwise relevant documents requiring context/review |
| `conflicts` | Pairs of conflicting document IDs |
| `recommended_documents` | Matching IDs only for `selected`; empty otherwise |
| `evidence` | Document ID, revision, and source path for applicable documents |

Review reasons are `metadata_unverified`, `missing_environment`, `missing_version_min`, and `missing_version_max_exclusive`. Missing context and metadata review can coexist. Follow-up answers are submitted in a new request; there is no conversation history.

For example, a version-2.5.0 production query with key rotation enabled under the platform identity reports `disable_key_rotation` with `must` from RB-050 and `must_not` from RB-051. These are catalog rules, not direct source quotations. A version-2.4.0 query with unknown key rotation asks whether rotation is enabled. An intern production query reports insufficient evidence without identifying restricted documents.

All result details are generated after access filtering. Paths are references, not download URLs; use the document ID and revision with the retrieval endpoint. The local browser workspace displays messages, next steps, context questions, review reasons, and conflict details. See [the interface guide](web-interface.md).

## Request and service errors

| HTTP code | Meaning |
|---|---|
| 401 | Missing or invalid credentials; includes `WWW-Authenticate: Bearer` |
| 404 | Document or revision missing, or inaccessible; identical generic response |
| 422 | Invalid request fields or values |
| 503 | Authentication configuration or evidence store unavailable |

Handled errors return a generic `detail` string without echoing credentials, invalid input, or database source rows. Responses use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Database failure never falls back to unrestricted local files.


## Document revision retrieval

`GET /v1/documents/RB-042/revisions/1` requires the same authentication as selection. The document ID must match uppercase letters, a hyphen, and digits (`[A-Z]+-[0-9]+`). Revision must be an integer from 1 through 2147483647. Invalid path values return 422; valid requests with missing or inaccessible evidence return `404 {"detail":"Document revision not found"}`. No separate existence check uses administrator access.

Successful JSON responses contain:

| Field | Meaning |
|---|---|
| `document_id`, `revision` | Requested stored identity and revision |
| `title` | Title saved with that revision |
| `content` | Stored Markdown text, not a reread of the current source file |
| `checksum` | Stored SHA-256 of content plus immutable metadata, using the ingestion serialization; not a content-only hash |
| `current_revision` | Current revision number under the same authorized document |
| `is_current` | Whether the requested revision is current |
| `revision_status` | Status saved in that revision's metadata; not a current applicability decision |

Current database permissions govern all revisions. Removing a role's access or revoking the current document blocks that role's old revisions as well. Historical approved text can remain readable while access is retained; it is not automatically a recommendation. Use selection to evaluate applicability. Policy changes affect subsequent database reads; already-returned content cannot be retracted.

Content is returned as a JSON string with no-store/nosniff headers, never rendered as HTML. The browser viewer displays Markdown as plain text using textContent; it does not render document HTML. This endpoint does not provide exact supporting spans, downloads by filesystem path, or edits. Database failures return generic 503 responses without fallback to source files.


## Conflict source citations

Each document in `conflict_details[].documents` now includes `citations` and `citation_status`. Each citation has `document_id`, `revision`, the normalized `rule`, `start_line`, `end_line`, `quote`, and `source_sha256`. Line numbers are one-based and inclusive; multiline quotes join those source lines with a newline. The hash covers the entire UTF-8 content, unlike the retrieval endpoint's combined content/metadata `checksum`.

`citation_status: available` means every matching claim on that document has a citation. `incomplete` means one or more lacks one; any available citations are still returned, and an entirely uncited document has an empty list. Conflict detection and recommendation withholding do not depend on citation availability. `basis` remains `catalog_rules`: the normalized rules are manually authored, and quotation text is supplied separately. Validation checks textual identity, not semantic entailment.

Quotes come from metadata validated against source content during ingestion and revalidated against stored content on database selection reads. Current row-level permissions are applied before those rows reach the application. The API never reads live filesystem documents to generate database-backed citations. Retrieval of the cited revision uses the existing endpoint and rechecks current permissions. See [citation authoring and revision rules](citations.md).

## Private draft endpoints

Authenticated users with an assigned role can create, list, and read their own unpublished drafts through `/v1/drafts`. Google-mode POSTs require the same Origin and request header as selection. Uploads use raw `text/markdown`, not JSON or multipart. See [the full request contract](drafts.md#api-contract). Separate submission endpoints record reviewer decisions on fixed snapshots; separate publisher endpoints can publish an approved snapshot; see [publication](publication.md#api).

`POST /v1/drafts/{uuid}/review` saves private metadata review progress using an expected revision and six editable string fields. It returns validation issues without granting approval; stale saves return 409. Draft detail includes the latest saved review. See [the review contract](drafts.md#edit-and-save-review-progress).

## Submission workflow endpoints

Owners submit complete saved review revisions; separately authorized reviewers inspect and decide them. Reading roles alone grant no reviewer access. See [the submission API and authority boundaries](submissions.md#api). Approval does not publish.
