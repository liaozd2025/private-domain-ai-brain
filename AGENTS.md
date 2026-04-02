# Repository Guidelines

## Project Structure & Module Organization
`src/` contains the application code. Use `src/main.py` as the FastAPI entrypoint. Keep HTTP and WebSocket handlers in `src/api/`, orchestration and routing logic in `src/agent/`, specialist agents in `src/subagents/`, reusable integrations in `src/tools/`, and persistence or profile logic in `src/memory/`. Prompt assets live under `src/skills/`. Put tests in `tests/` using `test_*.py`. Root-level ops files include `.env.example`, `docker-compose.yml`, and `scripts/init_db.sql`.

## Build, Test, and Development Commands
`pip install -e ".[dev]"` installs runtime and dev dependencies.
`python -m uvicorn src.main:app --reload` runs the API locally.
`docker-compose up -d` starts local infrastructure such as PostgreSQL and Milvus.
`pytest tests -v` runs the full test suite.
`pytest --cov=src tests` checks coverage for non-trivial changes.
`ruff check .` enforces lint and import order.
`mypy src` runs type checks defined in `pyproject.toml`.

## Coding Style & Naming Conventions
Target Python 3.11, use 4-space indentation, and keep lines within the configured 100-character limit. Follow Ruff’s import sorting. Use `snake_case` for modules, functions, and variables, `PascalCase` for classes, enums, and Pydantic models, and `UPPER_SNAKE_CASE` for constants. Preserve the current style: English identifiers, with concise Chinese docstrings or comments where they improve readability.

## Testing Guidelines
Use `pytest` and `pytest-asyncio`; mark async tests with `@pytest.mark.asyncio`. Name files `tests/test_<area>.py` and tests `test_<behavior>`. Mock LLM, database, and webhook integrations with `AsyncMock`, `MagicMock`, and `patch` instead of calling live services. Any change to routing, API schemas, or agent behavior should include a regression test.

## Commit & Pull Request Guidelines
This repository currently has no commit history, so use Conventional Commits from the start: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`. Keep commits focused on one concern. PRs should summarize the change, list verification commands, note config or schema impacts, and include sample requests, responses, or screenshots when API behavior changes.

## Deep Agents Standard-First Rule
For any new capability related to planning, skills, agent composition, tool orchestration, memory, handoff, or multi-agent behavior, check the current Deep Agents official docs first before designing a custom implementation.

- If Deep Agents already provides a standard capability, use the official mechanism by default.
- Only build a custom mechanism when the official capability clearly cannot satisfy the product requirement.
- When custom behavior is still required, document the gap explicitly in the implementation plan: what official capability was checked, why it was insufficient, and what minimal custom layer is being added.
- Do not create parallel ad-hoc systems when the same behavior can be expressed through standard Deep Agents primitives.

## Security & Configuration Tips
Copy `.env.example` to `.env` and never commit real API keys, database passwords, or webhook secrets. Verify `DATABASE_URL`, `UPLOAD_DIR`, and Milvus settings before local runs. Prefer `docker-compose` for shared development setup, and use `scripts/init_db.sql` when initializing the database manually.
