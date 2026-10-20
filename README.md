# OpsLens AI — local prototype

Select applicable fictional operational guidance using explicit metadata, before adding AI generation.

## Run the first demonstration

From this directory:

```sh
./uv-local sync --frozen
.venv/bin/python -m opslens.selector --role platform --version 2.4.0 --environment production --key-rotation true
.venv/bin/python -m opslens.selector --role platform --version 2.5.0 --environment production --key-rotation true
.venv/bin/python -m opslens.selector --role intern --version 2.4.0 --environment production --key-rotation true
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

Roles are explicit test inputs, not real user login. No API is exposed. Each persona has a different database login; the database prevents that login from reading another persona's restricted rows or modifying documents. The local operator owns all three passwords and can choose any persona. OIDC and user-to-persona mapping are not implemented. The restricted fixtures are fictional and visible to anyone with filesystem access.

Conflict rules are manually authored fixtures, not semantic conflict detection. Evidence references identify a file and revision. Stored versions include a checksum of their content and metadata; claim-level span validation and an authorized citation-content endpoint are still future work. There is no saved-answer history, OIDC, LLM, embedding generation, live telemetry, or action execution. The software-version input is provided by the caller, not verified against a live service. No effective-date policy is implemented in this slice.

Tests are development regression checks, not a held-out benchmark or a security guarantee. No paid service is used.

See `SETUP.md` for Python and local PostgreSQL instructions.

## Database-backed demonstration

After generating the local reader credentials as described in `SETUP.md`:

```sh
docker compose up -d --wait db
.venv/bin/python -m opslens.database bootstrap
.venv/bin/python -m opslens.database ingest
.venv/bin/python -m opslens.selector --source database --role platform --version 2.4.0 --environment production --key-rotation true
OPSLENS_TEST_DATABASE=1 .venv/bin/python -m unittest discover -s tests -v
```

Database integration tests create and remove a uniquely named `opslens_test_*` database. They never truncate the development database. Without the opt-in variable, integration tests are skipped; ordinary catalog and selector tests still run.

GitHub Actions runs the full suite and a pgvector smoke check for pull requests targeting `main` and pushes to `main`. It uses a standard Linux runner and a disposable PostgreSQL service with CI-only credentials. No local `.env`, paid model API, or deployed database is used. Actions are pinned to commit hashes and Python dependencies are installed from `uv.lock`.

This is synchronous local ingestion, not the future worker/job pipeline. The catalog is authoritative for permissions: reingesting its current revision reapplies its allowed roles. Removing a catalog entry does not delete or revoke a stored document; explicitly ingest a new revoked revision or change the current revision's permissions to an empty list. Older revisions cannot replace a newer current revision or its permissions. Ingestion uses a single advisory lock suitable for this small corpus. Administrative access remains trusted and can bypass database protections; immutable-row triggers are not tamper-proof storage.
