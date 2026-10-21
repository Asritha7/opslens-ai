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
OPSLENS_TEST_DATABASE=1 .venv/bin/python -m unittest discover -s tests -v
```

The suite currently contains 72 tests. Database tests create/drop a uniquely named `opslens_test_*` database and never truncate the development database. They use existing reader credentials without resetting their passwords. The admin account is needed to create/remove that temporary database. These are regression tests, not a held-out benchmark or a production security guarantee.

Coverage includes exact/multiline citation validation, stale fingerprints, invalid citation batches, legacy evidence, hidden quotations, version boundaries, permissions, conflicts, missing context, safe explanations, source provenance, ambiguous extraction, authority-field rejection, transactional ingestion, immutable revisions, raw database reader restrictions, bearer-key validation/revocation, authorized revision retrieval, historical access revocation, identical missing/denied responses, and API-to-database integration. File/database parity covers 72 role/version/environment/rotation combinations.

## GitHub workflow

GitHub Actions runs the full suite and a pgvector smoke check on pull requests into `main` and pushes to `main`. It installs locked dependencies and uses a disposable PostgreSQL service with CI-only credentials. The required job is named `Selector and PostgreSQL tests`; keep that name aligned with branch protection.

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
