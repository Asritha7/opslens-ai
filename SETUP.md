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
