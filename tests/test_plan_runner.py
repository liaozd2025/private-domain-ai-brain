"""Deep Agents plan runner 集成测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from deepagents.backends.filesystem import FilesystemBackend

from src.agent.plan_runner import DeepPlanRunner


def test_plan_runner_build_agent_uses_official_deepagents_skills_wiring():
    """plan runner 应按 Deep Agents 官方方式传入 skills 与受限 backend。"""
    with patch("src.agent.plan_runner.create_llm", return_value=MagicMock()):
        runner = DeepPlanRunner(checkpointer=MagicMock())

    with (
        patch.object(runner, "_build_tools", return_value=[]),
        patch("src.agent.plan_runner.create_deep_agent", return_value=MagicMock()) as mock_create,
    ):
        runner._build_agent(
            user_id="user_1",
            user_role="operator",
            channel="web",
            attachments=[],
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["skills"] == ["/skills"]

    backend = call_kwargs["backend"]
    assert isinstance(backend, FilesystemBackend)
    assert backend.cwd == (Path(__file__).resolve().parents[1] / "src").resolve()
    assert backend.virtual_mode is True


