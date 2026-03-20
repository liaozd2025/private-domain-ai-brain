"""数据分析子智能体 (Data Analysis Agent)

职责：
  - 解析用户上传的 Excel/CSV 文件
  - 在沙箱中执行 Python 分析代码
  - 生成图表（matplotlib/plotly）
  - 输出分析报告
"""

import os
import textwrap
import traceback
from functools import lru_cache
from pathlib import Path

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from src.agent.runtime import ModernToolAgent
from src.tools.file_tools import get_dataframe_info, read_uploaded_file

logger = structlog.get_logger(__name__)

AgentExecutor = None
create_tool_calling_agent = None
SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "data-analysis"
STORE_DIAGNOSIS_KEYWORDS = (
    "门店诊断",
    "五大指标",
    "客流量",
    "人头数",
    "体验率",
    "成交率",
    "成交均价",
    "行动计划",
    "经营利润",
    "毛利率",
)
STORE_DIAGNOSIS_FILE_KEYWORDS = (
    "五大指标",
    "行动计划",
    "门店诊断",
    "经营数据",
)


# ===== 沙箱执行 =====

ALLOWED_IMPORTS = {
    "pandas", "numpy", "matplotlib", "matplotlib.pyplot",
    "plotly", "plotly.express", "plotly.graph_objects",
    "scipy", "scipy.stats", "json", "math", "statistics",
    "collections", "itertools", "datetime", "re",
}


def _is_safe_code(code: str) -> tuple[bool, str]:
    """简单的代码安全检查"""
    dangerous_keywords = [
        "import os", "import sys", "import subprocess",
        "exec(", "eval(", "__import__",
        "open(", "file(", "input(",
        "socket", "urllib", "requests", "httpx",
        "shutil", "pathlib.Path(",
    ]
    for kw in dangerous_keywords:
        if kw in code:
            return False, f"不允许使用 '{kw}'"
    return True, ""


@tool
def run_python_analysis(code: str, file_path: str | None = None) -> str:
    """在沙箱中执行 Python 数据分析代码

    Args:
        code: Python 分析代码（使用 pandas/numpy/matplotlib）
              数据通过 `df` 变量访问（如果提供了 file_path）
              分析结果赋值给 `result` 变量
    file_path: 可选的数据文件路径（Excel/CSV），加载为 df 变量

    Returns:
        代码执行结果（result 变量的字符串表示）
    """
    # 安全检查
    is_safe, reason = _is_safe_code(code)
    if not is_safe:
        return f"代码安全检查未通过: {reason}"

    # 构建执行环境
    import matplotlib
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    matplotlib.use("Agg")  # 非交互式后端

    sandbox_globals = {
        "pd": pd,
        "np": np,
        "plt": plt,
        "__builtins__": {
            "print": print,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "list": list,
            "dict": dict,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "round": round,
            "sum": sum,
            "max": max,
            "min": min,
            "sorted": sorted,
            "abs": abs,
        },
    }

    # 加载数据文件
    if file_path and os.path.exists(file_path):
        suffix = Path(file_path).suffix.lower()
        if suffix in (".xlsx", ".xls"):
            sandbox_globals["df"] = pd.read_excel(file_path)
        elif suffix == ".csv":
            sandbox_globals["df"] = pd.read_csv(file_path, encoding="utf-8-sig")

    sandbox_locals = {"result": None}

    try:
        exec(textwrap.dedent(code), sandbox_globals, sandbox_locals)
        result = sandbox_locals.get("result")

        if result is None:
            return "代码执行完成，但未设置 `result` 变量。请在代码末尾添加 `result = ...`"

        return str(result)

    except Exception:
        return f"代码执行错误:\n{traceback.format_exc()}"


@tool
def generate_chart(
    file_path: str,
    chart_type: str,
    x_column: str,
    y_column: str,
    title: str = "",
    output_dir: str = "./uploads/charts",
) -> str:
    """生成数据可视化图表

    Args:
        file_path: 数据文件路径
        chart_type: 图表类型 (bar/line/pie/scatter/hist)
        x_column: X 轴列名
        y_column: Y 轴列名
        title: 图表标题
        output_dir: 输出目录

    Returns:
        生成的图表文件路径
    """
    import matplotlib
    import matplotlib.pyplot as plt
    import pandas as pd

    matplotlib.use("Agg")

    # 尝试加载中文字体
    try:
        plt.rcParams["font.sans-serif"] = ["SimHei", "Arial Unicode MS", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

    try:
        suffix = Path(file_path).suffix.lower()
        if suffix in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        elif suffix == ".csv":
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        else:
            return f"不支持的文件类型: {suffix}"

        if x_column not in df.columns:
            return f"列 '{x_column}' 不存在，可用列: {', '.join(df.columns)}"
        if y_column not in df.columns:
            return f"列 '{y_column}' 不存在，可用列: {', '.join(df.columns)}"

        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == "bar":
            ax.bar(df[x_column], df[y_column])
        elif chart_type == "line":
            ax.plot(df[x_column], df[y_column], marker="o")
        elif chart_type == "pie":
            ax.pie(df[y_column], labels=df[x_column], autopct="%1.1f%%")
        elif chart_type == "scatter":
            ax.scatter(df[x_column], df[y_column])
        elif chart_type == "hist":
            ax.hist(df[y_column], bins=20)
        else:
            return f"不支持的图表类型: {chart_type}，支持: bar/line/pie/scatter/hist"

        ax.set_title(title or f"{y_column} by {x_column}")
        ax.set_xlabel(x_column)
        ax.set_ylabel(y_column)
        plt.tight_layout()

        # 保存图表
        os.makedirs(output_dir, exist_ok=True)
        from uuid import uuid4
        chart_filename = f"chart_{uuid4().hex[:8]}.png"
        chart_path = os.path.join(output_dir, chart_filename)
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()

        return f"图表已生成: {chart_path}"

    except Exception:
        return f"图表生成失败: {traceback.format_exc()}"


# ===== Data Analysis Agent =====

DA_AGENT_TOOLS = [read_uploaded_file, get_dataframe_info, run_python_analysis, generate_chart]

BASE_DA_AGENT_SYSTEM_PROMPT = (
    "你是一个专业的数据分析助手，擅长分析私域运营相关的业务数据。\n\n"
    "## 工作流程\n\n"
    "1. **理解需求**：明确用户要分析什么、想得出什么结论\n"
    "2. **探索数据**：使用 `read_uploaded_file` 和 `get_dataframe_info` 了解数据结构\n"
    "3. **执行分析**：使用 `run_python_analysis` 编写 pandas 分析代码\n"
    "4. **可视化**：如有需要，使用 `generate_chart` 生成图表\n"
    "5. **输出报告**：给出清晰的分析结论和建议\n\n"
    "## 分析代码规范\n\n"
    "通过 run_python_analysis 工具传入 Python 代码，数据文件通过 file_path 参数指定。\n"
    "代码中使用 df 变量访问数据，分析结果赋值给 result 变量（字符串格式）。\n\n"
    "示例：store_sales = df.groupby('门店名称')['销售额'].sum().sort_values(ascending=False)\n"
    "result = '门店分析: ' + store_sales.to_string()\n\n"
    "## 输出规范\n\n"
    "分析报告包含：\n"
    "1. 数据概况（行数、关键指标）\n"
    "2. 核心发现（3-5 个关键洞察）\n"
    "3. 数据图表（如果生成了）\n"
    "4. 业务建议（基于数据的可行建议）\n"
)
DA_AGENT_SYSTEM_PROMPT = BASE_DA_AGENT_SYSTEM_PROMPT


def _attachment_search_text(attachments: list[dict] | None = None) -> str:
    parts: list[str] = []
    for attachment in attachments or []:
        for key in ("filename", "file_path", "sheet_name"):
            value = attachment.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def is_store_diagnosis_request(query: str = "", attachments: list[dict] | None = None) -> bool:
    """判断是否为美容门店五大指标诊断请求。"""
    query_text = query.lower()
    attachment_text = _attachment_search_text(attachments).lower()

    if any(keyword in query_text for keyword in STORE_DIAGNOSIS_KEYWORDS):
        return True
    if any(keyword in attachment_text for keyword in STORE_DIAGNOSIS_FILE_KEYWORDS):
        return True
    return False


def _read_skill_file(relative_path: str) -> str:
    path = SKILL_DIR / relative_path
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _load_store_diagnosis_skill_bundle() -> str:
    sections = [
        "# Skill\n" + _read_skill_file("SKILL.md"),
        "# Rules\n" + _read_skill_file("references/store-diagnosis-rules.md"),
        "# Cases\n" + _read_skill_file("references/store-diagnosis-cases.md"),
    ]
    return "\n\n".join(sections)


def build_data_analysis_system_prompt(
    query: str = "",
    attachments: list[dict] | None = None,
) -> str:
    """按请求类型构造运行时系统提示词。"""
    if not is_store_diagnosis_request(query, attachments):
        return BASE_DA_AGENT_SYSTEM_PROMPT

    return (
        BASE_DA_AGENT_SYSTEM_PROMPT
        + "\n\n"
        + "## 门店诊断模式\n\n"
        + "当前请求是美容门店五大指标诊断。你必须遵循以下要求：\n"
        + "1. 仅依据用户输入的数据、上传文件内容，以及下方规则资料进行分析。\n"
        + "2. 不调用知识库事实，不编造缺失数据，不擅自替用户补齐口径。\n"
        + "3. 数据不足时，先输出“数据完整性检查”和“需补充数据”，不要直接下结论。\n"
        + "4. 输出必须固定包含：数据完整性检查、五大指标诊断、核心问题排序、"
        + "通用经营建议、品牌化动作建议、行动计划表。\n"
        + "5. 行动计划表至少包含：项目、当前现状/差额、目标标准、核心动作、机制/话术、"
        + "责任人、预期目标。\n"
        + "6. 若由五大指标推算出的业绩与用户提供的业绩冲突，必须提示“数据口径可能不一致”。\n"
        + "7. 先给行业通用建议，再给品牌化动作建议；"
        + "品牌化动作只能作为第二层建议，不能替代诊断。\n\n"
        + "## 结构化输出模板\n\n"
        + "### 数据完整性检查\n"
        + "### 五大指标诊断\n"
        + "### 核心问题排序\n"
        + "### 通用经营建议\n"
        + "### 品牌化动作建议\n"
        + "### 行动计划表\n"
        + "### 风险与需补充数据\n\n"
        + _load_store_diagnosis_skill_bundle()
    )


class DataAnalysisAgent:
    """数据分析子智能体"""

    def __init__(self, llm):
        self.llm = llm
        self._agent = self._create_agent()

    def _create_agent(self, system_prompt: str = BASE_DA_AGENT_SYSTEM_PROMPT):
        if AgentExecutor is not None and create_tool_calling_agent is not None:
            from langchain_core.prompts import ChatPromptTemplate

            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            agent = create_tool_calling_agent(self.llm, DA_AGENT_TOOLS, prompt)
            return AgentExecutor(
                agent=agent,
                tools=DA_AGENT_TOOLS,
                verbose=False,
                max_iterations=8,
                handle_parsing_errors=True,
            )

        return ModernToolAgent(
            self.llm,
            DA_AGENT_TOOLS,
            system_prompt,
            recursion_limit=12,
            name="data-analysis-agent",
        )

    async def analyze(
        self,
        query: str,
        attachments: list[dict] = None,
        user_role: str = "unknown",
    ) -> str:
        """执行数据分析

        Args:
            query: 分析请求
            attachments: 已上传文件列表 [{file_id, filename, file_path, ...}]
            user_role: 用户角色

        Returns:
            分析报告
        """
        # 构建包含文件路径的请求
        enriched_query = query
        if attachments:
            file_info = "\n".join([
                f"- {a.get('filename', '未知文件')}: {a.get('file_path', '')}"
                for a in attachments
            ])
            enriched_query = f"[可用数据文件]:\n{file_info}\n\n[分析请求]: {query}"

        if user_role != "unknown":
            enriched_query = f"[用户角色: {user_role}]\n{enriched_query}"

        try:
            system_prompt = build_data_analysis_system_prompt(query, attachments)
            agent = self._agent
            if system_prompt != BASE_DA_AGENT_SYSTEM_PROMPT:
                agent = self._create_agent(system_prompt)

            if isinstance(agent, _FallbackDataAnalysisAgent):
                result = await agent.ainvoke(
                    {
                        "input": enriched_query,
                        "attachments": attachments or [],
                        "query": query,
                        "user_role": user_role,
                    }
                )
            else:
                result = await agent.ainvoke({"input": enriched_query})
            report = result.get("output", "分析失败，请重试。")
            logger.info("数据分析完成", query=query[:50], report_length=len(report))
            return report
        except Exception as e:
            logger.error("数据分析失败", error=str(e))
            return f"数据分析遇到问题: {str(e)}"


class _FallbackDataAnalysisAgent:
    """在缺少 legacy agent API 时的最小可用实现"""

    def __init__(self, llm, system_prompt: str = BASE_DA_AGENT_SYSTEM_PROMPT):
        self.llm = llm
        self.system_prompt = system_prompt

    async def ainvoke(self, payload: dict) -> dict:
        attachments = payload.get("attachments", [])
        context_sections = []

        for attachment in attachments:
            file_path = attachment.get("file_path", "")
            filename = attachment.get("filename", "未知文件")
            summary = read_uploaded_file.invoke({"file_path": file_path})
            details = get_dataframe_info.invoke({"file_path": file_path})
            context_sections.append(f"[文件: {filename}]\n{summary}\n\n{details}")

        response = await self.llm.ainvoke(
            [
                SystemMessage(content=self.system_prompt),
                HumanMessage(
                    content=(
                        f"{payload.get('input', '')}\n\n"
                        f"[文件内容概览]\n{chr(10).join(context_sections)}"
                    )
                ),
            ]
        )
        return {"output": getattr(response, "content", str(response))}
