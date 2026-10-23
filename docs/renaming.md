# Runreviq rename and compatibility

Runreviq replaces the former OpsLens AI product name. The repository is `Asritha7/runreviq`, the Python module is `runreviq`, and the project metadata, browser labels, documentation, and CI use the new name. Existing Python commands must change from `-m opslens.<module>` to `-m runreviq.<module>`. Database tests now use `RUNREVIQ_TEST_DATABASE=1`.

## Existing installations

- Update the Git remote to `https://github.com/Asritha7/runreviq.git`. The existing local checkout directory can keep its old name; moving it can break virtual-environment paths and running tools.
- Run `./uv-local sync --frozen`, then restart with `.venv/bin/python -m runreviq.api serve`. Sign in again after restarting.
- Private `.env`, `.local/api-keys.json`, and `.local/google-oidc.json` files stay in place. Existing Google client credentials and role assignments need no migration. The callback remains `http://127.0.0.1:8000/auth/google/callback`.
- Browser clients now send `X-Runreviq-Request: 1`; cookie names are `runreviq_session` and `runreviq_login`. Old cookies are not used. Saved theme preferences fall back to `opslens-theme` until a new choice is saved under `runreviq-theme`.

## Intentionally stable storage identifiers

The Docker Compose project `opslens-local`, named volume `opslens-local_postgres_data`, PostgreSQL database/schema `opslens`, database roles, migration ledger, advisory-lock identifiers, and draft owner setting keep their existing names. Applied migration files are unchanged because their checksums are recorded. These are internal compatibility identifiers, not the public product name. Renaming or recreating them is not needed for this rebrand and risks disconnecting existing data. Published documents, revisions, draft owners, and permissions remain unchanged.

## Google-managed labels

The Google Cloud project ID and OAuth client remain the existing resources. The consent-screen app name is managed separately in Google Auth Platform → Branding → App name; it may still show the former name until that label is updated. Do not recreate the project or client, rotate secrets, or change redirect URIs merely to rename the product.

The Docker database container display name is now `runreviq-db`, configured explicitly in `compose.yaml`. Existing installations can use `docker rename opslens-local-db-1 runreviq-db` without stopping PostgreSQL or changing its mounted volume. The Compose project/group still uses `opslens-local`; this does not change the product name.
