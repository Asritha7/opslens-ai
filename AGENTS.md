# Repository working agreements

- Keep this repository private unless the user explicitly requests a visibility change.
- Use main for reviewed milestones. Develop on focused branches such as chore/project-bootstrap, feat/runbook-selection, and feat/postgres-ingestion.
- Use descriptive Conventional Commit messages. Stage explicit paths and inspect every staged diff before committing.
- Never commit .env, credentials, local runtimes, virtual environments, database data, or downloaded model files.
- Run checks appropriate to each change. For the selector, run `.venv/bin/python -m unittest discover -s tests -v`.
- Open pull requests with the problem, resulting behavior, validation, and limitations. Do not merge without user authorization.
- Do not force-push, rewrite published history, or modify unrelated repositories.
- Preserve local-first operation; do not enable paid services or paid model fallbacks without explicit authorization.
