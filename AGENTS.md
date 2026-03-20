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

## Security & Configuration Tips
Copy `.env.example` to `.env` and never commit real API keys, database passwords, or webhook secrets. Verify `DATABASE_URL`, `UPLOAD_DIR`, and Milvus settings before local runs. Prefer `docker-compose` for shared development setup, and use `scripts/init_db.sql` when initializing the database manually.
