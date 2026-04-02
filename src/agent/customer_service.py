"""客服编排器与严格知识库客服智能体。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.orchestrator import create_llm
from src.memory.customer_service import (
    ACTIVE_HANDOFF_MESSAGE,
    STANDARD_HANDOFF_MESSAGE,
    get_customer_service_store,
)
from src.tools.milvus_tools import search_and_rerank

logger = structlog.get_logger(__name__)


@dataclass
class CustomerKBResult:
    can_answer: bool
    content: str
    reason: str


@dataclass
class CustomerServiceResult:
    content: str


class CustomerServiceKBAgent:
    """严格基于知识库的客服问答器。"""

    def __init__(self, llm=None):
        self.llm = llm or create_llm(streaming=False)

    async def query(self, question: str) -> CustomerKBResult:
        retrieval = search_and_rerank.invoke(
            {"query": question, "doc_type": "customer_service"}
        )
        if not retrieval:
            return CustomerKBResult(
                can_answer=False,
                content="",
                reason="未命中 customer_service 知识库",
            )

        if "未找到相关内容" in retrieval or retrieval.startswith("检索失败"):
            return CustomerKBResult(
                can_answer=False,
                content="",
                reason="未命中 customer_service 知识库",
            )

        prompt = (
            "你是私域运营客服助手。\n"
            "你只能基于给定资料回答，不得补充资料外事实。\n"
            "如果资料不足以准确回答，必须只输出：无法根据知识库准确回答。\n"
            "回答要简洁、自然、面向客户，不要暴露内部规则。"
        )
        response = await self.llm.ainvoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(
                    content=(
                        f"【知识库资料】\n{retrieval}\n\n"
                        f"【客户问题】\n{question}\n\n"
                        "请基于资料回答客户。"
                    )
                ),
            ]
        )
        content = getattr(response, "content", str(response)).strip()
        if not content or "无法根据知识库准确回答" in content:
            return CustomerKBResult(
                can_answer=False,
                content="",
                reason="知识库资料不足以准确回答",
            )
        return CustomerKBResult(
            can_answer=True,
            content=content,
            reason="命中 customer_service 知识库",
        )


class CustomerServiceSupervisor:
    """客服专用编排器。"""

    def __init__(
        self,
        *,
        kb_agent: CustomerServiceKBAgent | None = None,
        handoff_store=None,
        message_store=None,
    ):
        store = handoff_store or get_customer_service_store()
        self.kb_agent = kb_agent or CustomerServiceKBAgent()
        self.handoff_store = store
        self.message_store = message_store or store

    async def invoke(
        self,
        *,
        message: str,
        thread_id: str,
        user_id: str,
        channel: str,
        store_id: str | None = None,
    ) -> CustomerServiceResult:
        active_handoff = await self.handoff_store.get_active_handoff(thread_id)
        if active_handoff:
            await self.message_store.append_message(
                thread_id=thread_id,
                user_id=user_id,
                channel=channel,
                sender_type="customer",
                content=message,
            )
            return CustomerServiceResult(content=ACTIVE_HANDOFF_MESSAGE)

        await self.message_store.append_message(
            thread_id=thread_id,
            user_id=user_id,
            channel=channel,
            sender_type="customer",
            content=message,
        )

        if self._requested_human(message):
            logger.info("客户主动要求转人工", thread_id=thread_id, user_id=user_id)
            return await self._handoff(
                thread_id=thread_id,
                user_id=user_id,
                channel=channel,
                reason="用户主动要求人工客服",
                last_customer_message=message,
            )

        kb_result = await self.kb_agent.query(message)
        if not kb_result.can_answer:
            logger.info(
                "客服知识库无法回答，转人工",
                thread_id=thread_id,
                user_id=user_id,
                reason=kb_result.reason,
            )
            return await self._handoff(
                thread_id=thread_id,
                user_id=user_id,
                channel=channel,
                reason=kb_result.reason,
                last_customer_message=message,
            )

        await self.message_store.append_message(
            thread_id=thread_id,
            user_id=user_id,
            channel=channel,
            sender_type="ai",
            content=kb_result.content,
        )
        return CustomerServiceResult(content=kb_result.content)

    async def stream(
        self,
        *,
        message: str,
        thread_id: str,
        user_id: str,
        channel: str,
        store_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        result = await self.invoke(
            message=message,
            thread_id=thread_id,
            user_id=user_id,
            channel=channel,
            store_id=store_id,
        )
        for token in result.content:
            yield token

    async def _handoff(
        self,
        *,
        thread_id: str,
        user_id: str,
        channel: str,
        reason: str,
        last_customer_message: str,
    ) -> CustomerServiceResult:
        await self.handoff_store.create_or_refresh_handoff(
            thread_id=thread_id,
            user_id=user_id,
            channel=channel,
            reason=reason,
            last_customer_message=last_customer_message,
        )
        await self.message_store.append_message(
            thread_id=thread_id,
            user_id=user_id,
            channel=channel,
            sender_type="system",
            content=STANDARD_HANDOFF_MESSAGE,
        )
        return CustomerServiceResult(content=STANDARD_HANDOFF_MESSAGE)

    @staticmethod
    def _requested_human(message: str) -> bool:
        keywords = ("人工", "人工客服", "转人工", "真人", "客服")
        lowered = message.strip()
        return any(keyword in lowered for keyword in keywords)


_customer_service_supervisor: CustomerServiceSupervisor | None = None
_customer_service_supervisor_lock = asyncio.Lock()


async def get_customer_service_supervisor() -> CustomerServiceSupervisor:
    global _customer_service_supervisor
    if _customer_service_supervisor is not None:
        return _customer_service_supervisor
    async with _customer_service_supervisor_lock:
        if _customer_service_supervisor is None:
            _customer_service_supervisor = CustomerServiceSupervisor()
    return _customer_service_supervisor
