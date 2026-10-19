# OpsLens local development setup

The project has an isolated uv installation, managed Python runtime, and virtual environment.
No shell-profile changes or system Python replacements were made.

- uv: 0.13.1, installed from Astral's official installer
- Python: 3.12.15, downloaded by uv
- Architecture: macOS ARM64

From this directory:

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
docker compose stop db         # Stop it; keep saved data
```

Connection: host `127.0.0.1`, port `55432`, database `opslens`, bootstrap administrator `opslens_admin`.
The random password is in `.env` (owner-readable only, excluded from Git).
Use a separate restricted application role when implementing the backend; the bootstrap administrator must not be used for permission-enforced retrieval.

The named Docker volume `opslens-local_postgres_data` preserves data when the container stops or is recreated. It is not a backup. Do not use `docker compose down -v` unless intentionally erasing this project's database.

The database publishes only on localhost, has a 1 GB container memory limit and a 2-CPU limit, and does not automatically restart. Docker Desktop itself consumes additional resources.
No cloud account or paid API is involved.
