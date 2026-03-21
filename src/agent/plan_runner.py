"""Deep Agents 驱动的 plan 模式执行器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.tools import tool

from src.agent.orchestrator import build_system_prompt, create_llm
from src.config import settings
from src.subagents.attachment_analysis import AttachmentAnalysisAgent
from src.subagents.content_generation import ContentGenerationAgent
from src.subagents.data_analysis import DataAnalysisAgent
from src.subagents.knowledge_base import KBAgent
from src.tools.openclaw_tools import OpenClawToolkit

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEEPAGENTS_BACKEND_ROOT = PROJECT_ROOT / "src"
DEEPAGENTS_SKILL_SOURCES = ["/skills"]

PLAN_SYSTEM_PROMPT = """你现在运行在 plan 模式。

工作要求：
1. 对任何超过一步的任务，必须先调用 `write_todos` 生成计划，并保证至少一项是 `in_progress`
2. 计划生成后，再按需调用知识、数据、附件、内容、外部动作工具
3. 不要假装已经执行过工具；工具没有返回的结果不能编造
4. 如果用户只是要一个方案或拆解，请先给计划，再给简要执行建议
5. 始终使用简体中文，输出直接、专业、可执行
"""

TABULAR_FILE_TYPES = {"csv", "excel"}
TOOL_DISPLAY_NAMES = {
    "research_private_domain_knowledge": "检索知识库",
    "generate_operational_content": "生成运营内容",
    "analyze_uploaded_attachments": "分析附件",
    "analyze_uploaded_data": "分析表格数据",
}


@dataclass
class PlanRunResult:
    content: str
    plan: list[dict[str, str]]
    model: str


class DeepPlanRunner:
    """基于 Deep Agents 的计划执行器。"""

    def __init__(self, checkpointer: BaseCheckpointSaver | None = None):
        self.llm = create_llm(streaming=True)
        self.vision_llm = create_llm(
            provider=settings.vision_llm,
            model=settings.vision_model,
            streaming=False,
        )
        self.checkpointer = checkpointer

    async def invoke(
        self,
        *,
        message: str,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        channel: str = "web",
        attachments: list[dict] | None = None,
    ) -> PlanRunResult:
        attachments = attachments or []
        agent = self._build_agent(
            user_id=user_id,
            user_role=user_role,
            channel=channel,
            attachments=attachments,
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 200,
            },
        )
        plan = self._normalize_todos(result.get("todos", []))
        if not plan:
            plan = self._fallback_plan(message)

        from src.agent.runtime import extract_text_from_state

        return PlanRunResult(
            content=extract_text_from_state(result),
            plan=plan,
            model=settings.primary_model,
        )

    async def stream(
        self,
        *,
        message: str,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        channel: str = "web",
        attachments: list[dict] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        attachments = attachments or []
        agent = self._build_agent(
            user_id=user_id,
            user_role=user_role,
            channel=channel,
            attachments=attachments,
        )

        latest_plan = self._fallback_plan(message, in_progress=True)
        yielded_real_plan = False
        emitted_task_states: dict[str, str] = {
            item["task_id"]: item["status"] for item in latest_plan
        }

        yield {
            "type": "plan",
            "content": latest_plan,
            "thread_id": thread_id,
        }
        for item in latest_plan:
            yield {
                "type": "task",
                "content": item,
                "thread_id": thread_id,
            }

        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 200,
            },
            version="v2",
        ):
            kind = event.get("event")
            name = event.get("name")
            data = event.get("data", {})

            if kind == "on_tool_end" and name == "write_todos":
                plan = self._normalize_todos(data.get("input", {}).get("todos", []))
                if plan:
                    changed_tasks = self._collect_changed_tasks(plan, emitted_task_states)
                    latest_plan = plan
                    yielded_real_plan = True
                    yield {
                        "type": "plan",
                        "content": latest_plan,
                        "thread_id": thread_id,
                    }
                    yield {
                        "type": "step",
                        "content": latest_plan,
                        "thread_id": thread_id,
                    }
                    for task in changed_tasks:
                        yield {
                            "type": "task",
                            "content": task,
                            "thread_id": thread_id,
                        }
                continue

            if kind == "on_tool_start" and name != "write_todos":
                yield {
                    "type": "tool",
                    "content": {
                        "task_id": self._current_task_id(latest_plan),
                        "tool_name": name,
                        "display_name": TOOL_DISPLAY_NAMES.get(name, "执行外部动作"),
                        "status": "started",
                        "summary": self._build_tool_summary(name, data.get("input"), started=True),
                        "duration_ms": None,
                    },
                    "thread_id": thread_id,
                }
                continue

            if kind == "on_tool_end" and name != "write_todos":
                yield {
                    "type": "tool",
                    "content": {
                        "task_id": self._current_task_id(latest_plan),
                        "tool_name": name,
                        "display_name": TOOL_DISPLAY_NAMES.get(name, "执行外部动作"),
                        "status": "completed",
                        "summary": self._build_tool_summary(name, data.get("output")),
                        "duration_ms": None,
                    },
                    "thread_id": thread_id,
                }
                continue

            if kind == "on_tool_error" and name != "write_todos":
                yield {
                    "type": "tool",
                    "content": {
                        "task_id": self._current_task_id(latest_plan),
                        "tool_name": name,
                        "display_name": TOOL_DISPLAY_NAMES.get(name, "执行外部动作"),
                        "status": "failed",
                        "summary": self._truncate_summary(data.get("error") or "工具执行失败"),
                        "duration_ms": None,
                    },
                    "thread_id": thread_id,
                }
                continue

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                text = getattr(chunk, "content", "")
                if text:
                    yield {
                        "type": "token",
                        "content": text,
                        "thread_id": thread_id,
                    }

        if not yielded_real_plan:
            yield {
                "type": "step",
                "content": latest_plan,
                "thread_id": thread_id,
            }

        yield {
            "type": "done",
            "content": "",
            "thread_id": thread_id,
        }

    def _build_agent(
        self,
        *,
        user_id: str,
        user_role: str,
        channel: str,
        attachments: list[dict],
    ):
        tools = self._build_tools(
            user_id=user_id,
            user_role=user_role,
            channel=channel,
            attachments=attachments,
        )
        attachment_context = ""
        if attachments:
            filenames = ", ".join(a.get("filename", "未知文件") for a in attachments)
            attachment_context = f"\n当前可用附件：{filenames}"

        system_prompt = (
            build_system_prompt(user_role)
            + "\n\n"
            + PLAN_SYSTEM_PROMPT
            + attachment_context
        )

        return create_deep_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            skills=DEEPAGENTS_SKILL_SOURCES,
            # Scope filesystem access to `src/` only and enable virtual path guardrails.
            backend=FilesystemBackend(
                root_dir=DEEPAGENTS_BACKEND_ROOT,
                virtual_mode=True,
            ),
            checkpointer=self.checkpointer,
            name="private-domain-plan-runner",
        )

    def _build_tools(
        self,
        *,
        user_id: str,
        user_role: str,
        channel: str,
        attachments: list[dict],
    ) -> list[Any]:
        @tool
        async def research_private_domain_knowledge(question: str) -> str:
            """检索私域运营知识并返回带引用的专业答案。"""
            agent = KBAgent(llm=self.llm)
            return await agent.query(question, user_role=user_role)

        @tool
        async def generate_operational_content(requirement: str) -> str:
            """生成私域运营内容，例如活动方案、话术、SOP、海报文案。"""
            agent = ContentGenerationAgent(llm=self.llm)
            return await agent.generate(requirement, user_role=user_role, channel=channel)

        @tool
        async def analyze_uploaded_attachments(question: str) -> str:
            """分析当前已上传的图片、文档或混合附件。"""
            if not attachments:
                return "当前没有可分析的附件。"
            agent = AttachmentAnalysisAgent(text_llm=self.llm, vision_llm=self.vision_llm)
            return await agent.analyze(question, attachments=attachments, user_role=user_role)

        @tool
        async def analyze_uploaded_data(question: str) -> str:
            """分析当前已上传的表格数据（CSV/Excel）。"""
            tabular_attachments = [
                attachment
                for attachment in attachments
                if attachment.get("file_type") in TABULAR_FILE_TYPES
            ]
            if not tabular_attachments:
                return "当前没有可分析的表格附件。"
            agent = DataAnalysisAgent(llm=self.llm)
            return await agent.analyze(
                question,
                attachments=tabular_attachments,
                user_role=user_role,
            )

        tools: list[Any] = [
            research_private_domain_knowledge,
            generate_operational_content,
            analyze_uploaded_attachments,
            analyze_uploaded_data,
        ]
        tools.extend(OpenClawToolkit().get_tools())
        return tools

    def _normalize_todos(self, todos: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for index, todo in enumerate(todos, start=1):
            content = str(todo.get("content", "")).strip()
            status = str(todo.get("status", "pending")).strip() or "pending"
            if not content:
                continue
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            normalized.append({
                "task_id": f"task_{index}",
                "content": content,
                "status": status,
            })
        return normalized

    def _fallback_plan(self, message: str, *, in_progress: bool = False) -> list[dict[str, str]]:
        return [
            {
                "task_id": "task_1",
                "content": f"围绕用户请求制定并执行方案：{message[:60]}",
                "status": "in_progress" if in_progress else "completed",
            }
        ]

    def _collect_changed_tasks(
        self,
        plan: list[dict[str, str]],
        emitted_task_states: dict[str, str],
    ) -> list[dict[str, str]]:
        changed: list[dict[str, str]] = []
        for item in plan:
            task_id = item["task_id"]
            status = item["status"]
            if emitted_task_states.get(task_id) != status:
                emitted_task_states[task_id] = status
                changed.append(item)
        return changed

    def _current_task_id(self, plan: list[dict[str, str]]) -> str | None:
        for item in plan:
            if item.get("status") == "in_progress":
                return item.get("task_id")
        if plan:
            return plan[0].get("task_id")
        return None

    def _build_tool_summary(
        self,
        tool_name: str,
        payload: Any,
        *,
        started: bool = False,
    ) -> str:
        display_name = TOOL_DISPLAY_NAMES.get(tool_name, "外部动作")
        if started:
            return f"开始{display_name}"
        if payload is None:
            return f"{display_name}已完成"
        return self._truncate_summary(str(payload))

    def _truncate_summary(self, value: str, limit: int = 120) -> str:
        text = " ".join(str(value).split())
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."


_plan_runner: DeepPlanRunner | None = None
_plan_runner_lock = asyncio.Lock()


async def get_plan_runner() -> DeepPlanRunner:
    global _plan_runner
    if _plan_runner is not None:
        return _plan_runner
    async with _plan_runner_lock:
        if _plan_runner is None:
            from src.memory.checkpointer import get_checkpointer

            checkpointer = await get_checkpointer()
            _plan_runner = DeepPlanRunner(checkpointer=checkpointer)
            logger.info("Deep plan runner 初始化完成")
    return _plan_runner
