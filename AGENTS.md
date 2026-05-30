# Project Instructions for Codex

## Working Rules
- Preserve existing behavior unless the user explicitly requests behavior changes.
- Inspect the relevant modules before editing code, then keep changes small and reviewable.
- Do not perform broad rewrites, dependency upgrades, or public API renames unless the task requires them.
- Stage files deliberately; do not use broad `git add .` when unrelated files exist.

## Commit Content
- Commit messages must clearly state whether the change is `feat`, `fix`, `chore`, `docs`, or another appropriate type.
- Commit bodies should list the important behavior or tooling changes first, then secondary maintenance details.
- Include the validation commands that were run, and call out any checks that could not be run.

## Comments and Documentation
- Add Chinese comments or docstrings for new or modified public functions, public classes, core workflows, and non-obvious logic.
- Comments should explain intent, business context, edge cases, failure modes, and why a branch exists.
- Do not add comments that merely translate code, such as "遍历列表", "判断是否为空", or "调用函数".
- Add or update comments when touching complex condition branches, exception handling, async/concurrent work, caching, database access, LLM calls, prompt construction, retries, timeouts, rate limits, fallbacks, and degraded behavior.
- Keep third-party API names, protocol fields, error codes, and code keys in their original language.

## Python Style
- Target Python 3.12, matching the backend Docker image.
- Use type hints for new or modified functions when the surrounding code makes that practical.
- Use Google-style docstrings for public Python APIs that need documentation.
- Prefer readable names over abbreviations and keep functions focused.
- Avoid broad `except Exception` unless there is a clear recovery path; if it is necessary, explain the recovery or fallback intent.

## Frontend Style
- Keep React and TypeScript changes consistent with the existing Ant Design admin UI.
- Prefer explicit types for exported helpers, component props, API payloads, and non-obvious state.
- Add comments only for business rules, derived UI state, data-shape normalization, and edge cases that are not clear from the code.
- Do not disable TypeScript, ESLint, or formatting checks to hide a problem without explaining the reason.

## Validation
- For backend Python changes, run the relevant subset of:
  - `black --check backend`
  - `ruff check backend`
  - `mypy backend/app backend/scripts`
  - `pydocstyle backend/app`
  - `radon cc -nb backend/app backend/scripts`
  - `docker compose exec -T backend python -m unittest discover -s tests -q`
- For frontend changes, run the relevant subset of:
  - `cd frontend && npm run build`
  - `cd frontend && npm run lint`
  - `cd frontend && npm run format:check`
- Treat first-stage mypy, pydocstyle, and radon output as report-only unless the task explicitly says to make them blocking.
