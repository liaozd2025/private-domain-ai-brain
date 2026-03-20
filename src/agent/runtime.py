"""现代 LangChain / LangGraph 运行时适配层。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool


def extract_text_from_message(message: BaseMessage | Any) -> str:
    """尽量从 LangChain 消息对象中提取文本内容。"""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def extract_text_from_state(result: dict[str, Any]) -> str:
    """从 `create_agent` / `create_deep_agent` 返回的状态中提取最终答复文本。"""
    messages = result.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return extract_text_from_message(message)

    if messages:
        return extract_text_from_message(messages[-1])

    if "output" in result:
        return str(result["output"])

    return str(result)


class ModernToolAgent:
    """对 `create_agent` 的轻量封装，兼容旧的 `ainvoke({input: ...})` 调用方式。"""

    def __init__(
        self,
        llm: Any,
        tools: Sequence[BaseTool | Any],
        system_prompt: str,
        *,
        recursion_limit: int = 12,
        name: str | None = None,
    ) -> None:
        self._agent = create_agent(
            model=llm,
            tools=list(tools),
            system_prompt=system_prompt,
            name=name,
        )
        self._recursion_limit = recursion_limit

    async def ainvoke(self, payload: dict[str, Any]) -> dict[str, str]:
        query = payload.get("input", "")
        result = await self._agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config={"recursion_limit": self._recursion_limit},
        )
        return {"output": extract_text_from_state(result)}
