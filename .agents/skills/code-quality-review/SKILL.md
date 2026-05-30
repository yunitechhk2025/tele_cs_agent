---
name: code-quality-review
description: Review and improve this repository's comments, Python style, React/TypeScript style, and static-check workflow. Use when asked to add useful comments/docstrings, run code-quality checks, reduce lint/type/complexity issues, or keep Codex-generated changes aligned with AGENTS.md without unnecessary behavior changes.
---

# Code Quality Review

## Workflow
1. Read `AGENTS.md`, then inspect the files directly related to the request.
2. State the intended batch and scope before editing. Keep the write set small.
3. Preserve behavior unless the user explicitly asks for behavior changes.
4. Add Chinese comments or docstrings only where they explain intent, business context, edge cases, failure modes, or non-obvious choices.
5. Avoid comments that merely translate code operations.
6. Run the relevant checks from `AGENTS.md`. Treat first-stage `mypy`, `pydocstyle`, and `radon` output as report-only unless the task says otherwise.
7. Report files changed, important comments/docstrings added, checks run, remaining warnings, and risks.

## Python Review Rules
- Use Google-style docstrings for new or modified public functions/classes that need documentation.
- Prefer type hints for new or modified functions when the surrounding code supports them.
- Comment complex branches, exception handling, async/background jobs, caching, database access, LLM calls, prompt construction, retries, timeouts, rate limits, fallbacks, and degraded behavior.
- Do not rename public functions, classes, fields, or API routes only for style.
- Do not hide type problems with `Any` or lint suppressions unless the reason is documented.

## Frontend Review Rules
- Keep React/TypeScript edits consistent with the existing Ant Design admin UI.
- Add comments for derived UI state, URL/query synchronization, API payload normalization, and business rules that are not obvious from the component structure.
- Do not add broad ESLint disables. Prefer narrow fixes or a documented report-only finding.
- Use `npm run build`, `npm run lint`, and `npm run format:check` from `frontend` when frontend code or tooling changes.

## Static-Check Triage
- Fix formatting and safe lint issues first.
- Classify type, docstring, and complexity findings before changing logic.
- Refactor high-complexity functions only as a separate, explicitly scoped task.
- If checks are unavailable because dependencies are missing, state the install command and continue with checks that can run.
