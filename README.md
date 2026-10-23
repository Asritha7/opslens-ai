# Runreviq — local prototype

Select applicable fictional operational guidance using explicit metadata, before adding AI generation.

## Documentation

- [Setup and local commands](SETUP.md)
- [Architecture and current scope](docs/architecture.md)
- [Browser workspace and access controls](docs/web-interface.md)
- [API request and response contract](docs/api.md)
- [Private draft upload and preview](docs/drafts.md)
- [Metadata extraction and review](docs/metadata-proposals.md)
- [Validated claim citations](docs/citations.md)
- [Runbook authoring template](docs/runbook-template.md)
- [Tests, CI, and troubleshooting](docs/testing.md)
- [Contribution safeguards](AGENTS.md)

## Run the first demonstration

After completing [Python setup](SETUP.md), run from the repository root:

```sh
./uv-local sync --frozen
.venv/bin/python -m runreviq.selector --role platform --version 2.4.0 --environment production --key-rotation true
.venv/bin/python -m runreviq.selector --role platform --version 2.5.0 --environment production --key-rotation true
.venv/bin/python -m runreviq.selector --role intern --version 2.4.0 --environment production --key-rotation true
.venv/bin/python -m unittest discover -s tests -v
```

Expected outcomes: two compatible applicable documents; an unresolved conflict with no recommendation; insufficient authorized evidence.

## Data and rules

Nine manually authored Markdown documents live in `datasets/northstar`. `catalog.json` contains their manually authored metadata and normalized claims. Document revision and software version are separate fields.

- Filter allowed roles before inspecting applicability or exposing evidence.
- Only approved documents may qualify; document approval does not imply metadata verification.
- Match service, environment, and `[minimum, maximum)` software-version range.
- Only exact three-part numeric versions are supported. Prereleases and arbitrary version syntax are rejected.
- `key_rotation_enabled` in a document is either a required boolean or null (no requirement). Unknown query values cannot satisfy a required boolean.
- Missing critical metadata or unknown required query facts produce `needs_context_or_review`. This conservative prototype withholds all recommendations when any otherwise relevant authorized candidate is uncertain.
- Opposite `must` / `must_not` rules for the same manually normalized action among applicable documents produce `conflict`.
- Compatible documents may both be selected; no artificial winner is chosen.

## Current boundaries

The CLI defaults to local files. After the database setup below, `--source database` reads the current stored revisions through separate read-only database accounts with row-level security. Ingestion validates the local catalog, saves Markdown content and metadata checksums, and publishes the whole batch in one transaction. Repeating the same revision adds no duplicate; changing its content or metadata requires a new revision. Permissions remain current policy and can change without rewriting historical evidence. A revoked document has no reader access, including to old revisions.

CLI roles remain explicit test inputs. The local HTTP API authenticates bearer keys and derives the reader role from an owner-only server configuration; callers cannot supply their own role. Each persona has a different database login; the database prevents that login from reading another persona's restricted rows or modifying documents. The local operator owns all three passwords and can choose any persona. The three demo keys map to named demo identities, not verified human accounts. Optional Google OIDC login maps verified Google subjects to operator-assigned roles; see [Google login setup](docs/google-login.md). Self-service role assignment is not implemented. The restricted fixtures are fictional and visible to anyone with filesystem access.

Conflict rules are manually authored fixtures, not semantic conflict detection. Evidence references identify a file and revision. Stored versions include a checksum of their content and metadata; authorized revision-content retrieval is available through the API; manually authored claim citations are validated against exact source lines and content fingerprints. There is no saved-answer history, LLM, embedding generation, live telemetry, or action execution. The software-version input is provided by the caller, not verified against a live service. No effective-date policy is implemented in this slice.

Tests are development regression checks, not a held-out benchmark or a security guarantee. No paid service is used.

See `SETUP.md` for Python and local PostgreSQL instructions.

## Database-backed demonstration

After generating the local reader credentials as described in `SETUP.md`:

```sh
docker compose up -d --wait db
.venv/bin/python -m runreviq.database bootstrap
.venv/bin/python -m runreviq.database ingest
.venv/bin/python -m runreviq.selector --source database --role platform --version 2.4.0 --environment production --key-rotation true
RUNREVIQ_TEST_DATABASE=1 .venv/bin/python -m unittest discover -s tests -v
```

Database integration tests create and remove a uniquely named `opslens_test_*` database. They never truncate the development database. Without the opt-in variable, integration tests are skipped; ordinary catalog and selector tests still run.

GitHub Actions runs the full suite and a pgvector smoke check for pull requests targeting `main` and pushes to `main`. It uses a standard Linux runner and a disposable PostgreSQL service with CI-only credentials. No local `.env`, paid model API, or deployed database is used. Actions are pinned to commit hashes and Python dependencies are installed from `uv.lock`.

This is synchronous local ingestion, not the future worker/job pipeline. The catalog is authoritative for permissions: reingesting its current revision reapplies its allowed roles. Removing a catalog entry does not delete or revoke a stored document; explicitly ingest a new revoked revision or change the current revision's permissions to an empty list. Older revisions cannot replace a newer current revision or its permissions. Ingestion uses a single advisory lock suitable for this small corpus. Administrative access remains trusted and can bypass database protections; immutable-row triggers are not tamper-proof storage.

## Authenticated local API

The commands below use demo mode. [Google mode](docs/google-login.md) replaces demo keys with browser login and server-side sessions. Live local Google sign-in and permitted evidence retrieval were verified on 2026-10-22; credentials and role assignments remain private configuration, not repository content.

The implemented API is a loopback-only FastAPI service. `POST /v1/select` accepts service, software version, environment, and key-rotation context. A demo bearer key, or a Google session when configured, determines the identity and database reader role. `GET /v1/me` reports that identity; `GET /health` reports process liveness only. Invalid credentials cannot load evidence; malformed request fields are rejected. Database failures return a generic error without exposing source rows or credentials.

```sh
.venv/bin/python -m runreviq.api init-keys  # once; refuses to overwrite existing keys
.venv/bin/python -m runreviq.api serve
# In a second terminal, from this repository:
.venv/bin/python -m runreviq.client --persona platform --version 2.4.0 --environment production --key-rotation true
```

The operator client reads the selected key from `.local/api-keys.json` and sends it in the Authorization header; the persona is not sent as a request field. The operator holds all demo keys and can try all personas. Keys are random, stored owner-only, excluded from Git, and never printed by setup. See `SETUP.md` for revocation and limitations. No paid authentication provider is used.

## Metadata proposals and actionable results

A local extractor now reads explicit Markdown applicability fields and produces reviewable metadata with source-line provenance. Try:

```sh
.venv/bin/python -m runreviq.extraction docs/runbook-template.md
```

Missing, invalid, or ambiguous values are flagged rather than guessed. Every proposal requires review; permissions, approval, and verification are assigned separately by the trusted operator. This first extractor supports structured Markdown, not arbitrary prose or AI extraction, and does not publish proposals automatically. Extraction itself does not change published revisions.

Selection results now include a readable `message`, `next_steps`, missing-context `questions`, metadata `review_items`, and `conflict_details` describing opposing catalog rules and document references. These fields are available through the API and CLI. The original result fields remain available. Conflict documents now include exact passages when citations are available; the local browser workspace displays these outcomes and opens cited passages. Its System, Light, and Dark themes remember your appearance preference.

See [metadata proposals and result explanations](docs/metadata-proposals.md) for the supported format, review workflow, and response contract.

## Read supporting document revisions

Authenticated clients can call `GET /v1/documents/{document_id}/revisions/{revision}` to retrieve stored Markdown, title, checksum, and current-revision information. The database enforces current permissions for historical revisions too. Missing documents, missing revisions, and inaccessible revisions return the same 404 response. Reading a document does not mean it is recommended for the current situation.

See [the retrieval contract](docs/api.md#document-revision-retrieval) and [a local example](SETUP.md#read-a-document-revision). See [claim citations](docs/citations.md) for exact conflict passages. The browser viewer displays stored revisions as numbered plain text and highlights matching cited passages.

## Private draft intake

Signed-in users with an assigned role can upload Markdown in the browser, save an unpublished draft, and inspect proposed metadata, missing values, and source lines. Drafts persist in PostgreSQL and are scoped to the uploader, independently of published document permissions. They never enter guidance selection. Users can save corrected metadata as private review progress, with missing/invalid fields and stale-save conflicts shown explicitly. Approval and publishing remain unavailable. See [setup](SETUP.md#private-markdown-drafts) and [the draft contract](docs/drafts.md).

## Project rename

This project is now **Runreviq** (formerly OpsLens AI). Repository: https://github.com/Asritha7/runreviq. Python commands use `python -m runreviq.<module>`; see [rename and compatibility notes](docs/renaming.md) before updating an existing checkout.
