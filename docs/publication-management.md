# Published guidance management

Designated publishers can browse published documents, inspect their immutable revisions, and withdraw current approved guidance. This covers both uploaded publications and the fictional fixture catalog in the database. Reading or reviewer roles alone do not grant management access. Publisher assignments remain explicit and are checked on every request.

## Use the interface

1. Sign in with an assigned identity and publisher capability, then select **Load published documents** under **Manage published guidance**.
2. Each entry shows its title, current revision, current reading roles, publication/storage time, and lifecycle status. The list is ordered by document ID, with 50 entries per page and a **Next page** button. Reload starts at the first page.
3. Choose **Inspect DOCUMENT-ID** for history. Each revision has a status, publication time, and source-inspection button. Older revisions identify the current replacement revision.
4. To retire current approved guidance, enter a reason of 1–2,000 characters, acknowledge the effect, and select **Withdraw revision N**.
5. Success records the withdrawal and removes the revision from subsequent database-backed selection. In the current browser, old result/source panels are cleared and users are prompted to query again. History remains available.

Withdrawal is not deletion and does not revoke reading access. Authorized readers can open the old source with a clear warning and the recorded reason; publishers can inspect all published history through management endpoints. A publisher's normal reading role still governs ordinary evidence queries. The reason is visible to people authorized to read the document, so include only appropriate operational details.

## Status and replacement

- **Active:** current, approved, and not withdrawn. Applicability and metadata verification still determine whether it can be recommended for a particular query.
- **Withdrawn:** this revision was explicitly retired. Its original approval metadata remains unchanged; the separate withdrawal record determines its current availability.
- **Superseded:** a newer revision is current. Historical source is available, but it is not current guidance. If a superseded revision was also withdrawn, history shows the withdrawal and identifies the newer revision.
- Other stored catalog statuses such as **draft**, **revoked**, or **superseded** remain visible. They do not get a withdrawal button.

There is no automatic fallback to an older version when the current one is withdrawn. A newly approved, higher revision can be published through the existing workflow. It becomes current, while the prior withdrawal stays recorded. Republishing/reingesting the same revision cannot erase withdrawal or restore recommendations. An identical publication retry is only a receipt of a past action, not a reactivation.

Correcting metadata within an upload requires a new saved revision, independent approval, and publication. Source text remains immutable: corrected text requires a new upload and therefore a separate document ID. There is no cross-document replacement-link editor or one-click restore in this milestone.

## API

All management routes require assigned authentication plus publisher capability. Google-session POSTs retain Origin and `X-Runreviq-Request: 1` checks.

| Endpoint | Behavior |
|---|---|
| `GET /v1/publication-management/documents?after=RB-042` | List up to 50 documents; optional exclusive ID cursor; returns `next_after` or null |
| `GET /v1/publication-management/documents/{document_id}` | Current roles and complete revision history, including withdrawal reasons and opaque actor keys |
| `GET /v1/publication-management/documents/{document_id}/revisions/{revision}` | Exact stored source, metadata, checksum, lifecycle status, withdrawal |
| `POST /v1/publication-management/documents/{document_id}/withdraw` | Body `{"expected_revision":2,"reason":"Outdated recovery steps"}`; returns a withdrawal receipt |

IDs use uppercase letters followed by a hyphen and digits, at most 100 characters. Revisions are positive 32-bit integers. The server derives actor identity; unknown request fields are rejected. Missing access returns 401/403; missing document/revision returns 404; invalid values or non-approved current guidance return 422; changed current revision or an already-recorded different withdrawal returns 409; storage/configuration errors return generic 503.

Identical withdrawal retries by the same actor return the original receipt only while that revision remains current. Different reasons/actors cannot overwrite it. If a newer revision is published, stale withdrawal requests conflict rather than retiring the new revision. Publication, ingestion, and withdrawal share a transaction lock to serialize these decisions.

The ordinary authorized source endpoint adds `guidance_status` and `withdrawal` (reason and time). It does not expose the withdrawal actor. Existing `revision_status` remains the immutable recorded catalog status. Consumers should use the new status when displaying current usability.

## Storage and setup

Apply additive migration 006 with `.venv/bin/python -m runreviq.database bootstrap`, then restart the API. No new password, database login, paid service, or identity assignment is required. Existing source revisions and earlier applied migrations are untouched.

`opslens.document_withdrawals` stores document ID, revision, authenticated actor's opaque key, reason, and timestamp. Its primary key prevents multiple withdrawals for the same revision. The publisher login has SELECT/INSERT only, with an insert policy requiring its actor context and current revision. Evidence readers can read only reason/time/identifiers for documents permitted by current row-level access policy; they cannot read actor keys or mutate withdrawals. Database-backed selection excludes withdrawn current revisions. The immutable source tables are never updated by withdrawal.

The local operator/backend/database administrator remain trusted. Direct SQL source reads are historical access, not a recommendation API. File-mode CLI selection still reads the static fixtures and does not consult database withdrawal state; use `--source database` for managed guidance. Already-returned results in another browser or an in-flight request are not remotely retracted; run a new query or open the source to check current status. There are no push notifications, undo/restore UI, reason editing, retention deletion, or publisher-assignment UI.
