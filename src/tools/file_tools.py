"""文件处理工具集

支持：Excel/CSV 解析、PDF 文本提取、Word 解析
"""

import os
from pathlib import Path
from typing import Optional

import structlog
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)


def _read_excel(file_path: str) -> dict:
    """读取 Excel 文件，返回 sheet 数据"""
    import pandas as pd

    sheets = {}
    xf = pd.ExcelFile(file_path)
    for sheet_name in xf.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        sheets[sheet_name] = {
            "columns": df.columns.tolist(),
            "shape": list(df.shape),
            "preview": df.head(5).to_dict(orient="records"),
            "dtypes": df.dtypes.astype(str).to_dict(),
        }
    return sheets


def _read_csv(file_path: str) -> dict:
    """读取 CSV 文件"""
    import pandas as pd

    df = pd.read_csv(file_path, encoding="utf-8-sig")
    return {
        "columns": df.columns.tolist(),
        "shape": list(df.shape),
        "preview": df.head(5).to_dict(orient="records"),
        "dtypes": df.dtypes.astype(str).to_dict(),
    }


def _read_pdf(file_path: str) -> str:
    """提取 PDF 文本"""
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    texts = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n\n".join(texts)


def _read_word(file_path: str) -> str:
    """提取 Word 文档文本"""
    from docx import Document

    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])


@tool
def read_uploaded_file(file_path: str) -> str:
    """读取已上传的文件内容

    Args:
        file_path: 文件路径（由文件上传接口返回）

    Returns:
        文件内容摘要（Excel/CSV 返回结构信息和预览，PDF/Word 返回文本内容）
    """
    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"

    suffix = Path(file_path).suffix.lower()

    try:
        if suffix in (".xlsx", ".xls"):
            data = _read_excel(file_path)
            result = f"Excel 文件，共 {len(data)} 个 Sheet:\n"
            for sheet_name, info in data.items():
                result += f"\n**{sheet_name}**: {info['shape'][0]} 行 × {info['shape'][1]} 列\n"
                result += f"  列名: {', '.join(str(c) for c in info['columns'])}\n"
                result += f"  预览 (前5行):\n"
                for row in info["preview"]:
                    result += f"    {row}\n"
            return result

        elif suffix == ".csv":
            data = _read_csv(file_path)
            result = f"CSV 文件: {data['shape'][0]} 行 × {data['shape'][1]} 列\n"
            result += f"列名: {', '.join(str(c) for c in data['columns'])}\n"
            result += f"预览 (前5行):\n"
            for row in data["preview"]:
                result += f"  {row}\n"
            return result

        elif suffix == ".pdf":
            text = _read_pdf(file_path)
            return f"PDF 文档内容 (共 {len(text)} 字):\n{text[:3000]}{'...(截断)' if len(text) > 3000 else ''}"

        elif suffix in (".docx", ".doc"):
            text = _read_word(file_path)
            return f"Word 文档内容 (共 {len(text)} 字):\n{text[:3000]}{'...(截断)' if len(text) > 3000 else ''}"

        elif suffix == ".txt":
            with open(file_path, "r", encoding="utf-8-sig") as f:
                text = f.read()
            return f"文本文件内容:\n{text[:3000]}"

        else:
            return f"不支持的文件类型: {suffix}"

    except Exception as e:
        logger.error("读取文件失败", file_path=file_path, error=str(e))
        return f"读取文件失败: {str(e)}"


@tool
def get_dataframe_info(file_path: str) -> str:
    """获取表格文件的详细统计信息（用于数据分析前的探索）

    Args:
        file_path: Excel 或 CSV 文件路径

    Returns:
        详细的数据统计信息
    """
    import pandas as pd

    suffix = Path(file_path).suffix.lower()
    try:
        if suffix in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        elif suffix == ".csv":
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        else:
            return f"不支持的文件类型 {suffix}，只支持 Excel/CSV"

        result = f"数据形状: {df.shape[0]} 行 × {df.shape[1]} 列\n\n"
        result += "**数值列统计**:\n"
        desc = df.describe()
        result += desc.to_string() + "\n\n"

        null_counts = df.isnull().sum()
        if null_counts.any():
            result += "**空值统计**:\n"
            result += null_counts[null_counts > 0].to_string() + "\n"

        return result

    except Exception as e:
        return f"读取文件失败: {str(e)}"
