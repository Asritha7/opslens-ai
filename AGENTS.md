# Repository working agreements

- This repository is public by user request. Do not change visibility without explicit authorization; treat every committed file as public.
- Use main for reviewed milestones. Develop on focused branches such as chore/project-bootstrap, feat/runbook-selection, and feat/postgres-ingestion.
- Use descriptive Conventional Commit messages. Stage explicit paths and inspect every staged diff before committing.
- Never commit .env, credentials, local runtimes, virtual environments, database data, or downloaded model files.
- Run checks appropriate to each change. For the selector, run `.venv/bin/python -m unittest discover -s tests -v`.
- Open pull requests with the problem, resulting behavior, validation, and limitations. Do not merge without user authorization.
- Do not force-push, rewrite published history, or modify unrelated repositories.
- Preserve local-first operation; do not enable paid services or paid model fallbacks without explicit authorization.

- Preserve existing document revisions: changing fixture content or metadata requires a deliberate revision update, not incidental documentation cleanup.
- Extraction produces proposals only. Never derive access permissions, approval, or verification authority from document text.
- Keep README.md, SETUP.md, and the relevant docs/ guides consistent with implemented behavior. Label future capabilities explicitly.
- For database/API changes, run the full suite with OPSLENS_TEST_DATABASE=1 when the local database is available; tests must use their disposable database.
