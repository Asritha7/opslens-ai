# Controlled publication

Publication is a separate explicit action after independent approval. Reading and reviewer permissions do not grant publisher access. No assignments are automatic, and no paid services are used.

## Operator setup

Add the missing `PUBLISH_PASSWORD` with the credential-generation block in [SETUP](../SETUP.md), run `.venv/bin/python -m runreviq.database bootstrap`, then restart the API. Migration 005 is additive and preserves existing data and applied migration checksums. Initialize the private allowlist:

```sh
.venv/bin/python -m runreviq.publications init-publishers
```

This creates `.local/publishers.json` with mode 600 and empty `google` and `demo` lists, refusing to overwrite an existing file. The trusted operator can assign a verified subject to the matching list. The person must also have an assigned reading role. Permission is rechecked on every request; missing configuration denies access and malformed configuration fails closed. Removing an assignment cannot retract content already returned or cancel an authenticated request already executing.

Publishers can inspect all approved snapshots regardless of their reading role. They may also be authors or reviewers; independent review still requires a different authenticated identity from the author. Assign this capability deliberately. The backend and OS/database administrator remain trusted.

## Browser workflow

1. Select **Load publishing queue**. It shows up to 100 approved, unpublished eligible submissions, oldest first.
2. Open an approved revision and inspect its metadata, reviewer comment, and numbered original source.
3. Explicitly confirm you verified the metadata against the source and applicability.
4. Choose at least one reading role. These become the document's current access policy, including access to older published revisions.
5. Enter 1–20 distinct normalized action names, required/forbidden rules, and source line ranges. Use consistent names across documents so conflicting instructions can be compared. Each range must contain nonempty source text. The server constructs the exact quotation and source fingerprint; it does not infer or verify the semantic meaning of your claim.
6. Select **Publish approved revision**. Success shows the document ID, revision, and publication time. Invalid inputs, stale publication conflicts, unavailable storage, and denied access are shown explicitly.

This is a human attestation step, not an independent second review of publisher-entered claims. Claims are recorded in immutable published metadata. An approved snapshot may be published even if a newer draft exists: later draft edits never substitute for the approved snapshot. Publishing a newer revision prevents publication of older unpublished revisions.

Authors see publication information under **Check submission status**. Reviewers see whether a decided snapshot has been published. Guidance queries use the existing selector and current reading permissions; publication does not guarantee that a document matches a particular situation or resolves conflicts.

## API

All routes require an assigned authenticated identity; publisher routes additionally require the separate allowlist. Cookie POSTs retain Origin and request-header protection.

| Route | Result |
|---|---|
| `GET /v1/publisher-access` | `can_publish` for the current identity |
| `GET /v1/publications/queue` | Up to 100 eligible approved snapshots |
| `GET /v1/publications/{submission_id}` | Exact approved metadata, source, and reviewer comment |
| `POST /v1/publications/{submission_id}` | Publish with the request below; returns document ID, revision, `published: true`, publication time |

```json
{
  "metadata_verified": true,
  "allowed_roles": ["platform"],
  "claims": [{"action": "rotate_signing_keys", "rule": "must", "start_line": 12, "end_line": 13}]
}
```

Unknown fields are rejected. Actor identity, document ID, revision, checksum, quotation, and source fingerprint are server-derived. Missing or non-approved snapshots return 404; missing publisher access returns 403; invalid input returns 422; changed retry settings or an older revision returns 409; configuration/storage failure returns generic 503. Identical retries return the original receipt, without republishing or changing access—even if a later revision is now current. The receipt identifies a historical publication, not necessarily the current revision.

## Storage and boundaries

A stable `UPLOAD-<draft UUID as integer>` document ID separates upload lineage from fixture IDs. The document revision equals the saved metadata revision, so gaps are possible. Source and approved metadata are copied from immutable storage, never browser input. A logical `submission:<UUID>` source label is not a filesystem path. The stored-document viewer continues to use the database.

One transaction inserts the document/version and `opslens.publications` receipt, recording the publisher's opaque identity, initial reading roles, and time. The catalog-ingestion lock serializes writes and unique constraints prevent duplicates. Earlier published revisions are preserved; current reading permissions apply to the whole history. Readers cannot access the private publication ledger. Authors see only their own receipts; reviewers can read publication identifiers but not publisher identities or roles.

The dedicated `opslens_publish_operator` account can read approved snapshots and published evidence, insert versions/receipts, and update document current-revision/access columns. It cannot decide submissions, edit drafts or versions, delete publications, or assume reader/reviewer roles. Its credential is trusted backend authority: application validation enforces the mapping from approved snapshots to published evidence, while RLS limits snapshot visibility and receipt insertion to approved submissions. Never distribute this database credential to end users.

There is no publisher-management UI, claim editing after publication, withdrawal/revocation UI, notification, source editing, or merging of separately uploaded source lineages. Corrected metadata requires a new saved revision and independent approval; corrected source requires a new upload. The existing fixture ingestion CLI remains a trusted administrator path. File-based CLI selection reads fixtures only; use database mode for uploaded publications.
