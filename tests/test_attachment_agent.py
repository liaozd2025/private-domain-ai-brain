"""附件分析子智能体测试"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_attachment_agent_delegates_tabular_analysis():
    """纯表格附件应委托给数据分析子智能体"""
    from src.subagents.attachment_analysis import AttachmentAnalysisAgent

    text_llm = MagicMock()
    vision_llm = MagicMock()
    delegated_agent = MagicMock()
    delegated_agent.analyze = AsyncMock(return_value="表格分析结果")

    with patch("src.subagents.attachment_analysis.DataAnalysisAgent", return_value=delegated_agent):
        agent = AttachmentAnalysisAgent(text_llm=text_llm, vision_llm=vision_llm)
        result = await agent.analyze(
            query="分析这份销售表",
            attachments=[{"file_type": "csv", "filename": "sales.csv", "file_path": "/tmp/sales.csv"}],
            user_role="门店老板",
        )

    assert result == "表格分析结果"
    delegated_agent.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_attachment_agent_uses_vision_model_for_images(tmp_path):
    """图片附件应走视觉模型分析"""
    from src.subagents.attachment_analysis import AttachmentAnalysisAgent

    image_path = tmp_path / "poster.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image-data")

    text_llm = MagicMock()
    vision_llm = MagicMock()
    vision_llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="图片分析结果"))

    agent = AttachmentAnalysisAgent(text_llm=text_llm, vision_llm=vision_llm)
    result = await agent.analyze(
        query="这张图讲了什么",
        attachments=[{"file_type": "image", "filename": "poster.png", "file_path": str(image_path)}],
    )

    assert result == "图片分析结果"
    messages = vision_llm.ainvoke.await_args.args[0]
    human_message = messages[-1]
    assert any(part.get("type") == "image_url" for part in human_message.content)


@pytest.mark.asyncio
async def test_attachment_agent_summarizes_documents(tmp_path):
    """文档附件应读取文本后交给文本模型总结"""
    from src.subagents.attachment_analysis import AttachmentAnalysisAgent

    doc_path = tmp_path / "notes.txt"
    doc_path.write_text("今天门店复盘：复购率上涨，活动到店人数增加。", encoding="utf-8")

    text_llm = MagicMock()
    text_llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="文档总结结果"))
    vision_llm = MagicMock()

    agent = AttachmentAnalysisAgent(text_llm=text_llm, vision_llm=vision_llm)
    result = await agent.analyze(
        query="帮我总结这个文件",
        attachments=[{"file_type": "text", "filename": "notes.txt", "file_path": str(doc_path)}],
    )

    assert result == "文档总结结果"
    messages = text_llm.ainvoke.await_args.args[0]
    assert "活动到店人数增加" in str(messages[-1].content)
