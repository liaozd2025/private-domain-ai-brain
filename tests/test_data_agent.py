"""数据分析智能体测试"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def sample_csv(tmp_path):
    """创建测试 CSV 文件"""
    csv_content = """门店名称,月份,销售额,订单数
门店A,2024-01,50000,100
门店B,2024-01,80000,150
门店C,2024-01,30000,60
门店A,2024-02,55000,110
门店B,2024-02,85000,160
门店C,2024-02,28000,55
"""
    csv_file = tmp_path / "sales_data.csv"
    csv_file.write_text(csv_content, encoding="utf-8")
    return str(csv_file)


def test_read_uploaded_file_csv(sample_csv):
    """读取 CSV 文件应返回内容摘要"""
    from src.tools.file_tools import read_uploaded_file

    result = read_uploaded_file.invoke({"file_path": sample_csv})
    assert "门店名称" in result
    assert "销售额" in result
    assert "6" in result or "行" in result  # 包含行数信息


def test_read_uploaded_file_not_found():
    """不存在的文件应返回错误信息"""
    from src.tools.file_tools import read_uploaded_file

    result = read_uploaded_file.invoke({"file_path": "/nonexistent/file.csv"})
    assert "不存在" in result


def test_run_python_analysis_basic(sample_csv):
    """基础 Python 分析代码执行"""
    # 使用 run_python_analysis（不依赖 df，纯计算）
    code = """
result = sum([1, 2, 3, 4, 5])
"""
    # 直接调用工具
    from src.subagents.data_analysis import run_python_analysis
    result = run_python_analysis.invoke({"code": code})
    assert "15" in result


def test_run_python_analysis_with_dataframe(sample_csv):
    """带数据文件的 Python 分析"""
    from src.subagents.data_analysis import run_python_analysis

    code = """
total = df["销售额"].sum()
result = f"总销售额: {total}"
"""
    result = run_python_analysis.invoke({"code": code, "file_path": sample_csv})
    assert "总销售额" in result or "328000" in result


def test_run_python_analysis_allows_whitelisted_imports(sample_csv, tmp_path):
    """白名单 import 不应因缺少 __import__ 而失败。"""
    from src.subagents.data_analysis import run_python_analysis

    allowed_csv = tmp_path / "uploads" / "sales_data.csv"
    allowed_csv.parent.mkdir(parents=True, exist_ok=True)
    allowed_csv.write_text(Path(sample_csv).read_text(encoding="utf-8"), encoding="utf-8")

    code = f"""
import pandas as pd
df2 = pd.read_csv(r"{allowed_csv}")
result = f"行数: {{len(df2)}}"
"""
    with patch("src.subagents.data_analysis.settings.upload_dir", str(tmp_path / "uploads")):
        result = run_python_analysis.invoke({"code": code})

    assert "行数: 6" in result


def test_run_python_analysis_imported_pandas_keeps_upload_dir_guard(sample_csv, tmp_path):
    """即使通过 import pandas as pd，也不能绕过 upload_dir 路径限制。"""
    from src.subagents.data_analysis import run_python_analysis

    code = f"""
import pandas as pd
df2 = pd.read_csv(r"{sample_csv}")
result = "should not happen"
"""
    with patch("src.subagents.data_analysis.settings.upload_dir", str(tmp_path / "uploads")):
        result = run_python_analysis.invoke({"code": code})

    assert "不允许读取路径" in result


def test_run_python_analysis_blocks_dangerous_code():
    """危险代码应被拒绝"""
    from src.subagents.data_analysis import run_python_analysis

    code = "import os; os.system('ls'); result = 'done'"
    result = run_python_analysis.invoke({"code": code})
    assert "安全检查" in result or "不允许" in result


def test_store_diagnosis_request_detection_by_query_and_attachment(sample_csv):
    """门店诊断请求应被识别出来。"""
    from src.subagents.data_analysis import is_store_diagnosis_request

    assert is_store_diagnosis_request(
        query="请根据五大指标给我做门店经营诊断",
        attachments=[{"filename": "方彩珍：五大指标+行动策略指南.xlsx", "file_path": sample_csv}],
    )
    assert not is_store_diagnosis_request(
        query="帮我看哪个门店销售额最高",
        attachments=[{"filename": "sales_data.csv", "file_path": sample_csv}],
    )


def test_build_store_diagnosis_prompt_contains_required_sections(sample_csv):
    """门店诊断 prompt 应包含固定结构和动作层次。"""
    from src.subagents.data_analysis import build_data_analysis_system_prompt

    prompt = build_data_analysis_system_prompt(
        query="请做门店五大指标诊断",
        attachments=[{"filename": "王锦芝 五大指标.xlsx", "file_path": sample_csv}],
    )

    assert "数据完整性检查" in prompt
    assert "五大指标诊断" in prompt
    assert "通用经营建议" in prompt
    assert "品牌化动作建议" in prompt
    assert "行动计划表" in prompt
    assert "体验率" in prompt


def test_base_data_analysis_prompt_forbids_reimport_and_hardcoded_paths():
    """基础提示词应明确要求复用预置变量和 file_path 参数。"""
    from src.subagents.data_analysis import build_data_analysis_system_prompt

    prompt = build_data_analysis_system_prompt(query="帮我分析附件指标", attachments=[])

    assert "运行环境已预置 pd / np / plt" in prompt
    assert "不要在代码里硬编码" in prompt


@pytest.mark.asyncio
async def test_data_analysis_agent_uses_dynamic_prompt_for_store_diagnosis(sample_csv):
    """门店诊断请求应使用诊断专用 prompt 创建 agent。"""
    from src.subagents.data_analysis import DataAnalysisAgent

    default_agent = AsyncMock()
    default_agent.ainvoke = AsyncMock(return_value={"output": "默认分析"})
    diagnosis_agent = AsyncMock()
    diagnosis_agent.ainvoke = AsyncMock(return_value={"output": "门店诊断报告"})

    with patch.object(
        DataAnalysisAgent,
        "_create_agent",
        side_effect=[default_agent, diagnosis_agent],
    ) as mock_create:
        da = DataAnalysisAgent(llm=MagicMock())

        result = await da.analyze(
            query="请根据门店五大指标给我做诊断",
            attachments=[{"filename": "门店五大指标.xlsx", "file_path": sample_csv}],
        )

    assert result == "门店诊断报告"
    assert mock_create.call_count == 2
    diagnosis_prompt = mock_create.call_args_list[1].args[0]
    assert "行动计划表" in diagnosis_prompt
    assert "品牌化动作建议" in diagnosis_prompt


@pytest.mark.asyncio
async def test_data_analysis_agent(sample_csv):
    """数据分析 Agent 端到端测试"""
    from src.subagents.data_analysis import DataAnalysisAgent

    mock_llm = MagicMock()
    agent_mock = AsyncMock()
    agent_mock.ainvoke = AsyncMock(
        return_value={"output": "分析报告：门店B销售额最高，达80000元。"}
    )

    da = DataAnalysisAgent(llm=mock_llm)
    da._agent = agent_mock

    result = await da.analyze(
        query="哪个门店销售额最高",
        attachments=[{"filename": "sales_data.csv", "file_path": sample_csv}],
    )
    assert isinstance(result, str)
    assert len(result) > 0
    # 验证文件路径被注入请求
    call_input = agent_mock.ainvoke.call_args[0][0]["input"]
    assert sample_csv in call_input


def test_data_analysis_subagent_uses_skill_mount_and_runtime_bundle():
    """数据分析 Deep Agent 应挂载 skill，门店诊断运行时 prompt 仍应包含 references。"""
    from src.subagents.data_analysis import (
        DATA_ANALYSIS_SUBAGENT,
        build_data_analysis_system_prompt,
    )

    prompt = build_data_analysis_system_prompt(
        query="请根据门店五大指标做经营诊断",
        attachments=[{"filename": "门店五大指标.xlsx"}],
    )

    assert DATA_ANALYSIS_SUBAGENT["skills"] == ["/skills/data-analysis"]
    assert "门店数据分析诊断" in prompt
    assert "store-diagnosis-rules" in prompt.lower() or "默认阈值" in prompt
