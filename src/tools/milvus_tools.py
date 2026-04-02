"""Milvus 向量检索工具集

提供：
  - 向量搜索（语义检索）
  - 元数据过滤（混合搜索）
  - BGE 重排序
  - 带引用的结果格式化
"""

from functools import lru_cache
from typing import Any, Optional

import structlog
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config import settings

logger = structlog.get_logger(__name__)


# ===== Embedding（硅基流动 API）=====

@lru_cache(maxsize=1)
def get_embedding_client():
    """懒加载硅基流动 Embedding 客户端"""
    from openai import OpenAI
    logger.info("初始化硅基流动 Embedding 客户端", model=settings.embedding_model)
    return OpenAI(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
    )


@lru_cache(maxsize=1)
def get_reranker_model():
    """懒加载 BGE 重排序模型"""
    import os
    from FlagEmbedding import FlagReranker
    if settings.hf_token:
        os.environ["HF_TOKEN"] = settings.hf_token
    logger.info("加载 Reranker 模型", model=settings.reranker_model)
    return FlagReranker(
        settings.reranker_model,
        use_fp16=True,
        device=settings.embedding_device,
    )


# ===== Milvus 连接 =====

@lru_cache(maxsize=1)
def get_milvus_collection():
    """获取 Milvus Collection（懒加载）"""
    from pymilvus import Collection, connections

    conn_args = settings.milvus_connection_args
    connections.connect(alias="default", **conn_args)

    collection = Collection(settings.milvus_collection_name)
    collection.load()
    logger.info("Milvus Collection 加载完成", collection=settings.milvus_collection_name)
    return collection


# ===== 搜索结果模型 =====

class SearchResult(BaseModel):
    """单条检索结果"""
    id: str
    content: str
    score: float
    title: Optional[str] = None
    source: Optional[str] = None
    doc_type: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class SearchResults(BaseModel):
    """检索结果集"""
    results: list[SearchResult]
    query: str
    total_found: int


# ===== 核心工具函数 =====

def embed_query(query: str) -> list[float]:
    """将查询文本转换为向量（硅基流动 API）"""
    client = get_embedding_client()
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=query,
        encoding_format="float",
    )
    return response.data[0].embedding


def search_milvus_raw(
    query_vector: list[float],
    top_k: int = 10,
    filter_expr: str = "",
    output_fields: list[str] = None,
) -> list[dict]:
    """底层 Milvus 向量搜索"""
    collection = get_milvus_collection()

    search_params = {
        "metric_type": "COSINE",
        "params": {"nprobe": 16},
    }

    if output_fields is None:
        output_fields = ["id", "content", "title", "source", "doc_type", "metadata"]

    results = collection.search(
        data=[query_vector],
        anns_field="embedding",
        param=search_params,
        limit=top_k,
        expr=filter_expr or None,
        output_fields=output_fields,
    )

    hits = []
    for hit in results[0]:
        entity = hit.entity
        hits.append({
            "id": str(hit.id),
            "content": entity.get("content", ""),
            "score": float(hit.score),
            "title": entity.get("title", ""),
            "source": entity.get("source", ""),
            "doc_type": entity.get("doc_type", ""),
            "metadata": entity.get("metadata", {}),
        })

    return hits


def rerank_results(query: str, results: list[dict], top_k: int = 5) -> list[dict]:
    """BGE 交叉编码器重排序"""
    if not results:
        return results

    try:
        reranker = get_reranker_model()
        pairs = [[query, r["content"]] for r in results]
        scores = reranker.compute_score(pairs, normalize=True)

        # 更新分数并重排序
        for result, score in zip(results, scores):
            result["rerank_score"] = float(score)

        reranked = sorted(results, key=lambda x: x["rerank_score"], reverse=True)
        return reranked[:top_k]

    except Exception as e:
        logger.warning("重排序失败，使用原始排序", error=str(e))
        return results[:top_k]


def format_with_citations(query: str, results: list[dict]) -> str:
    """将检索结果格式化为带引用的答案"""
    if not results:
        return ""

    citations = []
    for i, result in enumerate(results, 1):
        title = result.get("title") or f"文档 {i}"
        source = result.get("source", "")
        content = result["content"][:500]  # 截断避免过长

        citation = f"[{i}] **{title}**"
        if source:
            citation += f" (来源: {source})"
        citation += f"\n{content}"
        citations.append(citation)

    return "\n\n".join(citations)


# ===== LangChain Tool 封装 =====

@tool
def search_knowledge_base(
    query: str,
    doc_type: Optional[str] = None,
    top_k: int = 10,
) -> str:
    """在私域运营知识库中搜索相关内容。

    Args:
        query: 搜索查询，用自然语言描述要查找的内容
        doc_type: 文档类型过滤（可选）: strategy/sop/template/case/policy
        top_k: 返回结果数量（默认 10）

    Returns:
        格式化的检索结果，包含内容和来源引用
    """
    try:
        query_vector = embed_query(query)

        filter_expr = ""
        if doc_type:
            filter_expr = f'doc_type == "{doc_type}"'

        raw_results = search_milvus_raw(
            query_vector=query_vector,
            top_k=top_k,
            filter_expr=filter_expr,
        )

        if not raw_results:
            return "知识库中未找到相关内容。"

        logger.info("知识库检索完成", query=query[:50], results_count=len(raw_results))
        return format_with_citations(query, raw_results)

    except Exception as e:
        logger.error("知识库搜索失败", error=str(e))
        return f"知识库搜索失败: {str(e)}"


@tool
def search_and_rerank(
    query: str,
    doc_type: Optional[str] = None,
) -> str:
    """在知识库中搜索并使用 BGE 重排序获取最相关内容（高精度模式）。

    Args:
        query: 搜索查询
        doc_type: 文档类型过滤（可选）

    Returns:
        重排序后的高精度检索结果
    """
    try:
        query_vector = embed_query(query)

        filter_expr = ""
        if doc_type:
            filter_expr = f'doc_type == "{doc_type}"'

        # 多取一些再重排
        raw_results = search_milvus_raw(
            query_vector=query_vector,
            top_k=settings.milvus_top_k,
            filter_expr=filter_expr,
        )

        if not raw_results:
            return "知识库中未找到相关内容。"

        # 重排序
        reranked = rerank_results(query, raw_results, top_k=settings.milvus_rerank_top_k)

        logger.info(
            "知识库检索+重排完成",
            query=query[:50],
            raw_count=len(raw_results),
            reranked_count=len(reranked),
        )
        return format_with_citations(query, reranked)

    except Exception as e:
        logger.error("知识库搜索+重排失败", error=str(e))
        return f"检索失败: {str(e)}"
