# OpsLens local development setup

The project has an isolated uv installation, managed Python runtime, and virtual environment.
The commands below keep project tooling inside the repository and do not require replacing macOS system Python. Any separately installed user-level Python is independent of this project.

- uv: 0.13.1, installed from Astral's official installer
- Python: 3.12.15, downloaded by uv
- Architecture: macOS ARM64

Run commands from the repository root. On a fresh clone, complete “Reproduce the Python setup” first.

For an existing installation:

```sh
./uv-local --version
./uv-local run --no-project --python .venv/bin/python python --version
source .venv/bin/activate
python --version
# When finished:
deactivate
```

Use `./uv-local` for future uv commands to keep its runtime and caches inside `.tools`.
The managed runtime lives in `.tools/python`; `.venv` depends on it.
Do not delete `.tools/python` while using this virtual environment.

## Reproduce the Python setup

Install uv from Astral's official installer into `.tools/bin`, without modifying shell profiles:

```sh
curl -LsSf https://astral.sh/uv/0.13.1/install.sh -o /tmp/opslens-uv-install.sh
UV_UNMANAGED_INSTALL="$PWD/.tools/bin" sh /tmp/opslens-uv-install.sh
./uv-local venv --python 3.12.15 --managed-python .venv
./uv-local sync --frozen
```

The existing Node.js, system Python, and shell configuration are not managed by this repository.

## Local database

Install Docker Desktop first. On a fresh clone, create `.env` once with a generated password (the command refuses to overwrite an existing file):

```sh
.venv/bin/python -c 'import os,secrets; fd=os.open(".env", os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600); os.write(fd, ("POSTGRES_PASSWORD="+secrets.token_urlsafe(32)+"\n").encode()); os.close(fd)'
```

Run these commands from this project directory in Terminal:

```sh
docker compose up -d --wait db   # Start database and wait until ready
docker compose ps              # Check its status
```

Connection: host `127.0.0.1`, port `55432`, database `opslens`, bootstrap administrator `opslens_admin`.
The random password is in `.env` (owner-readable only, excluded from Git).
The implemented database selector and API use separate restricted reader accounts. The bootstrap administrator is used for setup, ingestion, and disposable test-database administration, never permission-enforced retrieval.

The named Docker volume `opslens-local_postgres_data` preserves data when the container stops or is recreated. It is not a backup. Do not use `docker compose down -v` unless intentionally erasing this project's database.

The database publishes only on localhost, has a 1 GB container memory limit and a 2-CPU limit, and does not automatically restart. Docker Desktop itself consumes additional resources.
No cloud account or paid API is involved.

## Database schema, ingestion, and restricted readers

Install the locked Python dependencies with `./uv-local sync --frozen`.
Generate separate local passwords for each test persona. This preserves existing values:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import secrets
p = Path('.env')
text = p.read_text()
for role in ('PLATFORM', 'SECURITY', 'INTERN'):
    key = f'READER_{role}_PASSWORD'
    if not any(line.startswith(key + '=') for line in text.splitlines()):
        text += '\n' + key + '=' + secrets.token_urlsafe(32) + '\n'
p.write_text(text)
p.chmod(0o600)
PY

docker compose up -d --wait db
.venv/bin/python -m opslens.database bootstrap
.venv/bin/python -m opslens.database ingest
```

Bootstrap creates three non-superuser, read-only reader accounts and applies the numbered schema migration transactionally. It records the migration checksum and refuses edited applied migrations. It does not reset passwords for existing accounts. Keep `.env` safe; changing an existing password there alone does not rotate the database password.

The admin credential is used for setup, ingestion, and test-database administration. Database-backed selection uses `opslens_reader_platform`, `opslens_reader_security`, or `opslens_reader_intern`, with row access checked against the actual database login. `.env` is a local literal KEY=value file, not a shell script.

```sh
.venv/bin/python -m opslens.selector --source database --role intern --version 2.4.0 --environment production --key-rotation true
OPSLENS_TEST_DATABASE=1 .venv/bin/python -m unittest discover -s tests -v
```

The test command requires the local admin credential to create and remove its own disposable database. Reader-account names are shared with the development database, but existing role passwords are not altered. Tests use the same credentials; all test documents live in the disposable database.


## Local authenticated API

First complete database bootstrap and ingestion above. Install locked dependencies with `./uv-local sync --frozen`, then:

```sh
.venv/bin/python -m opslens.api init-keys
.venv/bin/python -m opslens.api serve
```

`init-keys` creates three random demo credentials in `.local/api-keys.json` with file mode 600 (only your OS account can read/write). It never overwrites an existing file or prints tokens. The `.local/` directory is Git-ignored. Do not paste this file into issues, screenshots, commits, or chat.

The server binds only to `127.0.0.1:8000`. If that port is already in use, it exits; stop or inspect your own conflicting process rather than terminating unrelated software. Stop this server with Ctrl+C. It does not install an auto-start service. Access logging is disabled, proxy headers are not trusted, and no browser docs/CDN or CORS access is enabled.

From another terminal in this repository, try:

```sh
.venv/bin/python -m opslens.client --persona platform --version 2.4.0 --environment production --key-rotation true
.venv/bin/python -m opslens.client --persona platform --version 2.5.0 --environment production --key-rotation true
.venv/bin/python -m opslens.client --persona intern --version 2.4.0 --environment production --key-rotation true
```

Expected: selected RB-042/RB-043; a conflict with no recommendation; insufficient authorized evidence. Use `--environment staging` with the intern key to retrieve its staging runbook. The client reads the secret internally; it never puts the token in shell arguments or output.

API contract:

- `GET /health`: public liveness response; does not promise database readiness.
- `GET /v1/me`: bearer authentication required; returns demo subject and role.
- `POST /v1/select`: bearer authentication required. JSON fields: `service` (nonempty identifier), `software_version` (exact numeric X.Y.Z), `environment` (`production` or `staging`), optional `key_rotation_enabled` (boolean or null). Extra fields, including `role`, are rejected. Responses retain the existing selection statuses and evidence references.
- 401: missing or invalid key. 422: invalid input. 503: credential configuration or database unavailable. Errors do not echo request values or database details. Responses use `Cache-Control: no-store`.

To revoke an individual key, remove its record from the private JSON file while preserving mode 600; new requests reload the file, so no restart is needed. Requests already authenticated may finish. To rotate a key, replace its token locally with `secrets.token_urlsafe(32)` and update the client that holds it. Never reuse database passwords as API tokens. An empty, malformed, missing, duplicate-identity, or overly readable credential file fails closed. There is no default/fallback key.

This is authentication by possession of local demo keys, not a production login system. The local operator controls all demo identities. Keys have no automatic expiry; there is no account lifecycle, OIDC, TLS, rate limiting, or audit history. Keep the server on loopback and do not expose it with a tunnel or public listener. API storage is read-only; ingestion remains a separate trusted local CLI. The API does not read files as a fallback when the database is unavailable.

Run `OPSLENS_TEST_DATABASE=1 .venv/bin/python -m unittest discover -s tests -v` for HTTP auth checks and real database integration, including requests under all three roles. Database test writes remain confined to a disposable `opslens_test_*` database.


## Extract and review metadata

```sh
.venv/bin/python -m opslens.extraction docs/runbook-template.md
```

This command needs neither PostgreSQL nor API credentials. It prints a proposal with source lines and a fingerprint, flags missing/ambiguous values, and never publishes it. Review is mandatory. Existing prose-only fixtures do not contain the structured fields and will report missing metadata. Follow [the extraction and review guide](docs/metadata-proposals.md) before transferring reviewed values into the catalog.

## Exercise all result states

With the database running and ingested, these additional requests demonstrate a follow-up question and a metadata-review requirement:

```sh
.venv/bin/python -m opslens.selector --source database --role platform --version 2.4.0 --environment production --key-rotation unknown
.venv/bin/python -m opslens.selector --source database --role platform --version 2.6.0 --environment production --key-rotation true
```

Results include messages, next steps, questions, review items, and conflict details. See [the API contract](docs/api.md) for fields and status meanings, and [testing and troubleshooting](docs/testing.md) for expected database logs.

## Stop local services

Stop the API with Ctrl+C in its terminal. When finished with database work:

```sh
docker compose stop db
```

This keeps the named volume. Start it again with `docker compose up -d --wait db`. Do not delete the volume to clear logs or resolve an ordinary test failure.


## Read a document revision

With the API running, run this in another terminal from the repository root. It reads the local platform credential without printing it and requests revision 1 of RB-042:

```sh
.venv/bin/python - <<'PYTHON'
import json
from urllib.request import Request, urlopen
from opslens.api import KEY_FILE, read_keys
record = next(r for r in read_keys(KEY_FILE) if r['subject'] == 'demo-platform')
request = Request('http://127.0.0.1:8000/v1/documents/RB-042/revisions/1',
                  headers={'Authorization': 'Bearer ' + record['token']})
with urlopen(request, timeout=10) as response:
    print(json.dumps(json.load(response), indent=2))
PYTHON
```

The response includes stored content, title, revision, checksum, and whether it is current. A missing or inaccessible document/revision gives the same 404 response. See [the API contract](docs/api.md#document-revision-retrieval) for historical-access rules and checksum semantics. This example only reads evidence and does not publish or modify documents.


## Publish and inspect conflict citations

The catalog advances only RB-050 and RB-051 to revision 2 to add reviewed citations; their Markdown text is unchanged. To publish these additions to an existing database, run:

```sh
.venv/bin/python -m opslens.database ingest
.venv/bin/python -m opslens.selector --source database --role platform --version 2.5.0 --environment production --key-rotation true
```

The existing revision 1 rows are preserved. Repeat ingestion adds no duplicate versions. A fresh database starts with the revisions present in the catalog, so it will not contain revision 1 of these two documents unless imported separately. Existing databases that have not ingested revision 2 continue to return explicitly incomplete citations for the legacy conflict. See [the citation guide](docs/citations.md).
