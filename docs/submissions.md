# Submission and independent reviewer decisions

This workflow submits a specific saved metadata review for an independent decision. It does not publish a document, grant document-reading roles, or feed the selector. `approved` means only that a reviewer approved the submitted snapshot; it does not set the published catalog's approval or verification fields.

## Author flow

1. Save complete metadata with no field issues. The latest saved review is the version eligible for submission.
2. Read the sharing notice and select **Submit saved revision N**. This exposes the full original Markdown, original extraction/provenance, and that saved metadata revision to all designated reviewers. Unsaved edits are excluded.
3. Use **Check submission status** to see pending/approved/changes-requested status and the reviewer comment.
4. If changes are requested, save a new metadata revision and submit it. The previous submission and decision remain unchanged. Source Markdown is immutable; changed source requires a new upload.

Retries of the same current revision return the existing submission without changing its decision. Saving newer metadata does not move an earlier submission to the newer revision. Submission of an outdated revision returns 409. Unsubmitted drafts and later unsubmitted metadata revisions remain private. There is currently no withdrawal, reassignment, notification, or submission deletion.

## Reviewer authority and setup

Reading roles (`platform`, `security`, `intern`) do not grant reviewer authority. A reviewer needs both an existing assigned reading role and an explicit subject entry in the operator-owned `.local/reviewers.json` file. This grants access to submitted documents from other authors, regardless of their evidence-reading role. Grant it only to intended reviewers.

Initialize an empty allowlist with:

```sh
.venv/bin/python -m runreviq.submissions init-reviewers
```

It refuses to overwrite an existing file and creates no assignments. Missing configuration means no reviewers. Malformed or overly readable configuration fails closed. Keep mode 600; do not commit the file. The shape is:

```json
{"google": [], "demo": []}
```

The trusted operator may add a verified Google subject string to `google`, or an existing demo subject to `demo`. These are separate namespaces. Never copy a subject from unverified document text. Assignments are reloaded for every reviewer request; removal blocks subsequent requests, but cannot retract already-returned content or undo a request already authenticated.

No real reviewer is enabled automatically. For a meaningful independent review, use a different person's assigned identity. Demo identities are operator-controlled and demonstrate mechanics only. Self-review is blocked by authenticated identity in the API and by the review-account insert policy. The local OS owner, backend, and database administrator remain trusted and are not cryptographically isolated.

## Reviewer flow

Select **Load reviewer queue**. Unauthorized accounts see an explanation. Authorized reviewers see up to 100 pending submissions, oldest first, excluding their own. Open a submission, inspect its metadata, original extraction/source lines, and source text. Choose **Request changes** or **Approve this revision**, enter a nonempty comment (at most 2,000 characters), and select **Record decision**.

Each submission has one final decision. Concurrent reviewers cannot overwrite one another: the second save receives 409 and must reload. A new review round uses a new saved metadata revision. A successful decision displays that approval alone has not published the document. Subsequent publication is a separately authorized action. All document and comment content is rendered as plain text.

## API

All endpoints require an assigned authenticated identity. Cookie-based POSTs retain the Origin and `X-Runreviq-Request: 1` checks.

| Endpoint | Contract |
|---|---|
| `POST /v1/drafts/{uuid}/submit` | Owner; JSON `{"revision": 1}`; returns submission ID, revision, the current publication flag |
| `GET /v1/drafts/{uuid}/submissions` | Owner; submission history with status, comment, submitted/decided times |
| `GET /v1/reviewer-access` | Reports `can_review` from the private allowlist |
| `GET /v1/submissions` | Reviewer only; pending queue (maximum 100) |
| `GET /v1/submissions/{uuid}` | Reviewer only, another author's submitted source and exact metadata snapshot |
| `POST /v1/submissions/{uuid}/decision` | Reviewer only; JSON `{"decision":"approved","comment":"Reviewed source and applicability"}`; returns recorded status, comment, time, `published: false` |

Unknown request fields are rejected. Reviewer identity and draft ownership are server-derived. Missing/denied/self-review targets return 404; unauthorized reviewer access returns 403; invalid metadata/comments return 422; stale submission/already-decided conflicts return 409; configuration/storage failures return generic 503. The owner history does not expose raw reviewer subjects. The database stores the reviewer's opaque identity key for operator inspection.

## Storage and migration

Migration 004 adds immutable submission and decision records. Submission references `(draft_id, revision)` in the append-only metadata review table. Draft-owner connections can insert/read their own submissions and read their own decisions, but cannot decide. The new `opslens_review_operator` account can read submitted source/snapshots and insert independent decisions, with no update/delete, publication, or role-management permissions. Database locks and unique keys prevent duplicate submissions and overwritten decisions. RLS restricts submitted visibility; the application and operator holding the database credentials remain trusted.

Existing installations add a private `REVIEW_PASSWORD` through the setup credential-generation block, run `.venv/bin/python -m runreviq.database bootstrap`, and restart the API. Existing passwords, applied migration files, source documents, metadata reviews, and published revisions are preserved. No paid services are required.
