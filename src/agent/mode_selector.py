"""自动选择 chat / plan 执行模式。"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

RequestedMode = Literal["auto", "chat", "plan"]
ResolvedMode = Literal["chat", "plan"]

PLAN_PATTERNS = [
    r"先规划再执行",
    r"先计划再执行",
    r"先出方案再执行",
    r"分步骤",
    r"拆成步骤",
    r"一步一步",
    r"行动计划",
    r"待办",
    r"todo",
    r"分阶段",
    r"规划.*执行",
    r"执行.*规划",
]
CHAT_PATTERNS = [
    r"^你好[呀啊吗]?$",
    r"^您好[呀啊吗]?$",
    r"^谢谢",
    r"^早上好$",
    r"^晚上好$",
    r"^帮我分析",
    r"^分析一下",
    r"^帮我写",
    r"^写一份",
]

# 门店经营数据检测 — 文件名关键词
_STORE_OP_FILENAME_KEYWORDS = (
    "门店经营", "五大指标", "行动计划", "门店诊断",
    "经营数据", "门店数据", "销售数据", "经营报告",
)

# 门店经营数据检测 — 列头关键词（至少命中 2 个才触发，降低误判）
_STORE_OP_COLUMN_KEYWORDS = (
    "客流量", "成交率", "成交均价", "体验率",
    "营业额", "毛利率", "经营利润", "人头数",
    "门店名称", "店名",
)
_STORE_OP_COLUMN_MIN_HITS = 2


class LLMModeDecision(BaseModel):
    """LLM 自动模式判定结果。"""

    resolved_mode: ResolvedMode = Field(description="最终执行模式")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=200)


MODE_SELECTOR_PROMPT = """你是一个执行模式选择器，只判断用户请求应该走 chat 还是 plan。

选择 `plan` 的条件：
- 用户明确要求先规划再执行、拆步骤、制定待办、分阶段推进
- 任务需要跨多个能力链路配合完成
- 明显需要先列计划，再逐步执行

选择 `chat` 的条件：
- 普通问答、知识咨询、单一内容生成、单一数据分析、单一附件理解
- 不需要显式计划编排

要求：
1. 除非非常明确需要 plan，否则保守返回 chat
2. 只返回结构化结果，不要解释额外内容
"""


class ModeSelector:
    """自动模式选择器。"""

    def __init__(self, llm=None):
        self.llm = llm
        self._structured_llm = (
            llm.with_structured_output(LLMModeDecision) if llm is not None else None
        )

    async def resolve_mode(
        self,
        *,
        message: str,
        requested_mode: RequestedMode = "auto",
        context: str = "",
        attachments: list[dict] | None = None,
        user_role: str = "unknown",
        channel: str = "web",
    ) -> dict[str, str | float]:
        if requested_mode in {"chat", "plan"}:
            return self._build_result(
                requested_mode=requested_mode,
                resolved_mode=requested_mode,
                selection_source="explicit",
                confidence=1.0,
                reason="显式指定模式",
            )

        heuristic = self._resolve_by_heuristic(message)
        if heuristic:
            return self._build_result(
                requested_mode="auto",
                resolved_mode=heuristic,
                selection_source="heuristic",
                confidence=0.93 if heuristic == "plan" else 0.9,
                reason="命中模式选择规则",
            )

        # 附件包含门店经营数据 → 强制 plan 模式
        if attachments and self._detect_store_operation_data(attachments):
            return self._build_result(
                requested_mode="auto",
                resolved_mode="plan",
                selection_source="heuristic",
                confidence=0.95,
                reason="附件包含门店经营数据，自动切换为 plan 模式",
            )

        attachment_summary = ", ".join(
            attachment.get("file_type", "unknown")
            for attachment in (attachments or [])
        ) or "none"
        prompt = (
            f"[用户角色]\n{user_role}\n\n"
            f"[渠道]\n{channel}\n\n"
            f"[附件类型]\n{attachment_summary}\n\n"
            f"[对话上下文摘要]\n{context or 'none'}\n\n"
            f"[当前消息]\n{message}"
        )

        try:
            self._ensure_llm()
            decision = await self._structured_llm.ainvoke(
                [
                    SystemMessage(content=MODE_SELECTOR_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            return self._build_result(
                requested_mode="auto",
                resolved_mode=decision.resolved_mode,
                selection_source="llm",
                confidence=decision.confidence,
                reason=decision.reason,
            )
        except Exception as exc:
            logger.warning("自动模式选择失败，降级为 chat", error=str(exc))
            return self._build_result(
                requested_mode="auto",
                resolved_mode="chat",
                selection_source="fallback",
                confidence=0.0,
                reason=f"自动模式选择失败，保守降级: {str(exc)}",
            )

    def _detect_store_operation_data(self, attachments: list[dict]) -> bool:
        """判断附件是否为门店经营数据（文件名关键词 or 列头 peek）。"""
        tabular_exts = {".xlsx", ".xls", ".csv"}

        for att in attachments:
            filename = att.get("filename", "").lower()
            file_path = att.get("file_path", "")
            ext = Path(file_path).suffix.lower() if file_path else ""

            # 1. 文件名关键词（无 I/O）
            if any(kw in filename for kw in _STORE_OP_FILENAME_KEYWORDS):
                logger.debug("门店经营数据命中(文件名)", filename=filename)
                return True

            # 2. 列头 peek（仅读首行，I/O 极小）
            if ext in tabular_exts and file_path:
                try:
                    import pandas as _pd
                    if ext in (".xlsx", ".xls"):
                        cols = _pd.read_excel(file_path, nrows=0).columns.tolist()
                    else:
                        cols = _pd.read_csv(file_path, nrows=0).columns.tolist()
                    cols_str = " ".join(str(c) for c in cols)
                    hits = sum(1 for kw in _STORE_OP_COLUMN_KEYWORDS if kw in cols_str)
                    if hits >= _STORE_OP_COLUMN_MIN_HITS:
                        logger.debug("门店经营数据命中(列头)", cols=cols[:10], hits=hits)
                        return True
                except Exception as exc:
                    logger.debug("列头 peek 失败，跳过", file=file_path, error=str(exc))

        return False

    def _resolve_by_heuristic(self, message: str) -> ResolvedMode | None:
        normalized = re.sub(r"\s+", " ", message).strip().lower()
        if not normalized:
            return "chat"

        for pattern in PLAN_PATTERNS:
            if re.search(pattern, normalized):
                return "plan"

        for pattern in CHAT_PATTERNS:
            if re.search(pattern, normalized):
                return "chat"

        return None

    def _ensure_llm(self) -> None:
        if self._structured_llm is not None:
            return

        from src.agent.orchestrator import create_llm
        from src.config import settings

        self.llm = create_llm(
            provider=settings.router_llm,
            model=settings.router_model,
            streaming=False,
        )
        self._structured_llm = self.llm.with_structured_output(LLMModeDecision)

    def _build_result(
        self,
        *,
        requested_mode: RequestedMode,
        resolved_mode: ResolvedMode,
        selection_source: str,
        confidence: float,
        reason: str,
    ) -> dict[str, str | float]:
        return {
            "requested_mode": requested_mode,
            "resolved_mode": resolved_mode,
            "selection_source": selection_source,
            "confidence": confidence,
            "reason": reason,
        }


_mode_selector: ModeSelector | None = None
_mode_selector_lock = asyncio.Lock()


async def get_mode_selector() -> ModeSelector:
    global _mode_selector
    if _mode_selector is not None:
        return _mode_selector
    async with _mode_selector_lock:
        if _mode_selector is None:
            _mode_selector = ModeSelector()
            logger.info("Mode selector 初始化完成")
    return _mode_selector
