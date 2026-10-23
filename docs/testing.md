# Tests, CI, and troubleshooting

## Run checks

After [Python setup](../SETUP.md):

```sh
./uv-local sync --frozen
.venv/bin/python -m unittest discover -s tests -v
```

The ordinary run exercises extraction, selection, catalog validation, and API tests; database integration tests are explicitly skipped. For the full suite, complete database bootstrap first, then:

```sh
docker compose up -d --wait db
RUNREVIQ_TEST_DATABASE=1 .venv/bin/python -m unittest discover -s tests -v
```

The suite currently contains 116 Python tests. Database tests create/drop a uniquely named `opslens_test_*` database and never truncate the development database. They use existing reader credentials without resetting their passwords. The admin account is needed to create/remove that temporary database. These are regression tests, not a held-out benchmark or a production security guarantee.

Coverage includes exact/multiline citation validation, stale fingerprints, invalid citation batches, legacy evidence, hidden quotations, version boundaries, permissions, conflicts, missing context, safe explanations, source provenance, ambiguous extraction, authority-field rejection, transactional ingestion, immutable revisions, raw database reader restrictions, bearer-key validation/revocation, authorized revision retrieval, historical access revocation, identical missing/denied responses, and API-to-database integration. File/database parity covers 72 role/version/environment/rotation combinations.

## Browser checks

Node.js 20 or later is needed only to run the JavaScript tests; there are no npm dependencies or frontend build step:

```sh
node --check runreviq/web/app.js
node --test tests/web.test.cjs
```

The fourteen tests execute the production script against a small mocked DOM and fetch implementation. They cover credential handling, disconnect and stale-response races, safe text rendering, historical revision labels, clearing failed document loads, and 401 resets. These are interaction-logic tests, not full browser automation.

Manual browser checks against the local database covered sign-in, missing-context follow-up, selected guidance, conflict quotes and highlighted source lines, metadata review, intern insufficient evidence, and reload clearing access. A 390px viewport had no horizontal page overflow. Manual checks supplement the automated suite.

## GitHub workflow

GitHub Actions runs the full Python suite, fourteen JavaScript interaction tests, and a pgvector smoke check on pull requests into `main` and pushes to `main`. It installs locked dependencies and uses a disposable PostgreSQL service with CI-only credentials. The required job is named `Selector and PostgreSQL tests`; keep that name aligned with branch protection.

Main requires pull requests, an up-to-date branch with passing required checks, and resolved conversations. Protection applies to admins; force pushes/deletion are blocked. The solo-developer configuration requires zero additional approving reviews. Use descriptive commits on focused branches and merge only with user authorization. Never bypass checks to merge.

## Common local messages

| Symptom | Explanation or next step |
|---|---|
| PostgreSQL initialization, CREATE DATABASE/EXTENSION | Normal first-run setup |
| Initial fast shutdown followed by startup | Normal container initialization sequence |
| Checkpoint starting/complete | Routine database disk persistence |
| Immutable-version / permission-denied errors during tests | Expected negative tests that verify prohibited writes and role switching are blocked; correlate with the test run |
| Database unavailable | Check Docker Desktop, `docker compose ps`, bootstrap, and local credentials |
| Reader password was edited in `.env` | The database password is not automatically rotated; restore the matching credential or deliberately rotate the account |
| API 401 | Credential missing, unknown, or revoked |
| API authentication 503 | Check that the key file exists, is valid, has unique records, and mode 600 |
| Existing keys on init | Expected refusal to overwrite; use the existing file |
| Port 8000 already in use | Inspect the existing process; do not terminate unrelated services |
| Extraction reports missing fields | The source must use the explicit Applicability format; prose is not inferred |

The container's local `trust` authentication rules concern sockets and loopback inside the container. The host application connects through the published port using password authentication. Access to Docker/container administration is trusted.

Do not delete database volumes, suppress error logging, or reset credentials merely to clear expected test logs. See [architecture](architecture.md) for boundaries and [metadata proposals](metadata-proposals.md) for extraction review.

## Google authentication checks

The full suite includes offline OIDC tests with generated RSA keys and a mocked exchange. Browser logic tests also cover cookie-based session restoration, unassigned users, logout, and clearing evidence after role denial. No real Google credentials or network requests are needed in CI. A live Google sign-in, initially unassigned account, local role assignment, session restoration, and authorized evidence query were verified on 2026-10-22; see [the verification record](google-login.md#recorded-local-verification--2026-10-22). Each installation still needs its own Google setup.

Demo API and database tests explicitly disable Google mode, so adding real local OAuth configuration cannot change their behavior. Expired login flows and sessions are checked through HTTP endpoints using a controlled clock.

## Draft checks

Draft tests cover file validation and byte limits, authenticated owner derivation, same-role account isolation, uniform missing/denied responses, per-owner quota, saved proposal persistence, RLS insert checks, and the draft writer’s inability to read or change published evidence. Integration writes stay in disposable databases. Browser interaction tests cover raw Markdown upload, safe preview text, saved draft loading, and disconnect races. A manual browser check uploaded and reopened the fictional template against a disposable database and inspected the extracted fields and source lines.

Review coverage includes incomplete/invalid fields, forbidden authority fields, owner-scoped persistence, original-source preservation, stale revision conflicts, append-only grants, RLS, UI error retention, and logout races.
