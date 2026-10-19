# OpsLens AI — local prototype

Select applicable fictional operational guidance using explicit metadata, before adding AI generation.

## Run the first demonstration

From this directory:

```sh
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

This CLI reads local files, not the running PostgreSQL database. Database ingestion is the next integration step. The catalog is trusted, hand-authored test data; untrusted upload validation and immutable ingestion are not implemented yet.

Roles are explicit test inputs, not real login or an authentication boundary. No API is exposed. The restricted fixtures are fictional and visible to anyone with filesystem access.

Conflict rules are manually authored fixtures, not semantic conflict detection. Evidence references identify a file and revision; claim-level span validation and content hashing are still future work. There is no saved-answer history, OIDC, LLM, embedding generation, live telemetry, or action execution. The software-version input is provided by the caller, not verified against a live service. No effective-date policy is implemented in this slice.

Tests are development regression checks, not a held-out benchmark or a security guarantee. No paid service is used.

See `SETUP.md` for Python and local PostgreSQL instructions.
