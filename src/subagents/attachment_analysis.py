"""附件分析子智能体"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.subagents.data_analysis import DataAnalysisAgent
from src.tools.file_tools import read_uploaded_file

logger = structlog.get_logger(__name__)

IMAGE_FILE_TYPES = {"image"}
TABULAR_FILE_TYPES = {"csv", "excel"}
DOCUMENT_FILE_TYPES = {"pdf", "word", "text"}


class AttachmentAnalysisAgent:
    """统一处理图片、文档和混合附件分析"""

    def __init__(self, text_llm, vision_llm):
        self.text_llm = text_llm
        self.vision_llm = vision_llm

    async def analyze(
        self,
        query: str,
        attachments: list[dict] | None = None,
        user_role: str = "unknown",
    ) -> str:
        attachments = attachments or []
        if not attachments:
            return "未检测到可分析的附件。"

        tabular_attachments = [a for a in attachments if a.get("file_type") in TABULAR_FILE_TYPES]
        image_attachments = [a for a in attachments if a.get("file_type") in IMAGE_FILE_TYPES]
        document_attachments = [a for a in attachments if a.get("file_type") in DOCUMENT_FILE_TYPES]

        if tabular_attachments and not image_attachments and not document_attachments:
            data_agent = DataAnalysisAgent(llm=self.text_llm)
            return await data_agent.analyze(
                query=query,
                attachments=tabular_attachments,
                user_role=user_role,
            )

        if image_attachments and not tabular_attachments and not document_attachments:
            return await self._analyze_images(query, image_attachments, user_role)

        context_sections: list[str] = []

        if document_attachments:
            context_sections.append(self._build_document_context(document_attachments))

        if tabular_attachments:
            data_agent = DataAnalysisAgent(llm=self.text_llm)
            table_result = await data_agent.analyze(
                query=query,
                attachments=tabular_attachments,
                user_role=user_role,
            )
            context_sections.append(f"[表格分析结果]\n{table_result}")

        if image_attachments:
            image_result = await self._analyze_images(query, image_attachments, user_role)
            context_sections.append(f"[图片分析结果]\n{image_result}")

        if not context_sections:
            return "暂不支持该附件类型。"

        return await self._summarize_attachment_context(query, context_sections, user_role)

    async def _analyze_images(
        self,
        query: str,
        attachments: list[dict],
        user_role: str,
    ) -> str:
        content = [
            {
                "type": "text",
                "text": (
                    "你是一个图片分析助手。请根据用户问题理解图片内容，"
                    f"给出简洁、准确的中文结论。\n[用户角色: {user_role}]\n[用户问题]: {query}"
                ),
            }
        ]

        for attachment in attachments:
            file_path = attachment.get("file_path", "")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._file_to_data_url(file_path)},
                }
            )

        response = await self.vision_llm.ainvoke([HumanMessage(content=content)])
        return self._extract_message_content(response)

    async def _summarize_attachment_context(
        self,
        query: str,
        context_sections: list[str],
        user_role: str,
    ) -> str:
        messages = [
            SystemMessage(
                content=(
                    "你是一个附件分析助手。请根据提供的附件内容，"
                    "直接回答用户问题；如果是多个附件，请合并成一份自然语言结论。"
                )
            ),
            HumanMessage(
                content=(
                    f"[用户角色: {user_role}]\n"
                    f"[用户问题]: {query}\n\n"
                    f"{chr(10).join(context_sections)}"
                )
            ),
        ]
        response = await self.text_llm.ainvoke(messages)
        return self._extract_message_content(response)

    def _build_document_context(self, attachments: list[dict]) -> str:
        sections = []
        for attachment in attachments:
            file_path = attachment.get("file_path", "")
            filename = attachment.get("filename", "未知文件")
            extracted = read_uploaded_file.invoke({"file_path": file_path})
            sections.append(f"[文档: {filename}]\n{extracted}")
        return "\n\n".join(sections)

    def _file_to_data_url(self, file_path: str) -> str:
        path = Path(file_path)
        size = path.stat().st_size
        if size > 20 * 1024 * 1024:
            raise ValueError(f"图片文件过大（{size} bytes），上限 20MB")
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _extract_message_content(self, response) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        return str(content)
