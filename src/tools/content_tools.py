"""内容生成工具集

提供：
  - 模板加载（活动方案、SOP、话术框架）
  - 平台适配（朋友圈/抖音/小红书/企微）
  - 品牌调性指南
"""

import json
from pathlib import Path
from typing import Optional

import structlog
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)


# ===== 模板库 =====

CONTENT_TEMPLATES = {
    "朋友圈文案": {
        "structure": "开头钩子（1句）+ 核心价值（2-3句）+ 行动召唤（1句）+ emoji点缀",
        "length": "150字以内",
        "tone": "生活化、有温度、有画面感",
        "example": "🌟 周末限定！买一送一\n两件好货，只花一件的钱\n今天下单，明天到家\n戳链接 ↓ 带上你的朋友一起薅羊毛！",
    },
    "小红书笔记": {
        "structure": "标题（带数字/关键词）+ 首图文案 + 正文（分段）+ 标签",
        "length": "500-1000字",
        "tone": "真实种草感、有干货、有个人经验",
        "example": "标题：门店社群运营3个月，复购率提升40%！（附完整SOP）\n正文：...",
    },
    "活动方案": {
        "structure": "活动名称 + 活动背景/目标 + 时间节点 + 活动内容 + 奖励设置 + 传播路径 + 执行步骤 + 预期效果",
        "length": "800-2000字",
        "tone": "清晰、结构化、可执行",
        "example": "",
    },
    "SOP文档": {
        "structure": "目的 + 适用范围 + 名词解释 + 流程步骤（含负责人/时限） + 注意事项 + 常见问题",
        "length": "500-3000字（视流程复杂度）",
        "tone": "清晰、无歧义、可操作",
        "example": "",
    },
    "销售话术": {
        "structure": "开场白 + 需求挖掘话术 + 产品介绍话术 + 异议处理 + 促成成交 + 售后跟进",
        "length": "300-800字",
        "tone": "自然、有说服力、不生硬",
        "example": "",
    },
    "企微推文": {
        "structure": "开头（触发兴趣）+ 内容主体 + 引导互动/行动",
        "length": "200-500字",
        "tone": "亲切、专业、有行动导向",
        "example": "",
    },
    "抖音脚本": {
        "structure": "前3秒钩子 + 问题提出 + 解决方案展示 + 价值证明 + 行动号召",
        "length": "60-120秒视频脚本",
        "tone": "快节奏、有冲击力、口语化",
        "example": "",
    },
    "社群公告": {
        "structure": "重要程度标识 + 公告内容 + 时间/地点/联系方式 + 注意事项",
        "length": "100-300字",
        "tone": "简洁、清晰、有亲和力",
        "example": "",
    },
}

PLATFORM_RULES = {
    "wecom": {
        "name": "企业微信",
        "limits": {"text": 4000, "image": 1},
        "features": ["图文消息", "链接卡片", "小程序"],
        "best_practices": ["开头直接切题", "使用数字和清单", "一条消息一个主题"],
    },
    "moments": {
        "name": "朋友圈",
        "limits": {"text": 1500, "image": 9},
        "features": ["图片", "视频", "外链"],
        "best_practices": ["前几行决定是否展开", "emoji 增加可读性", "避免硬广感"],
    },
    "xiaohongshu": {
        "name": "小红书",
        "limits": {"text": 1000, "image": 9},
        "features": ["标签", "话题", "地点打卡"],
        "best_practices": ["标题带数字/关键词", "真实种草感", "多图更佳", "标签 3-5 个"],
    },
    "douyin": {
        "name": "抖音",
        "limits": {"duration": "15s-10min"},
        "features": ["贴纸", "滤镜", "BGM"],
        "best_practices": ["前3秒必须抓眼球", "字幕配合口播", "音乐节奏匹配"],
    },
    "web": {
        "name": "通用/网页",
        "limits": {},
        "features": ["Markdown", "链接", "代码块"],
        "best_practices": ["结构清晰", "重点加粗", "可以使用Markdown格式"],
    },
}

BRAND_GUIDELINES = {
    "tone": "专业而不失亲切，有温度有干货",
    "avoid": ["虚假承诺", "夸大宣传", "竞品贬低", "低俗内容"],
    "keywords": ["私域", "精细化运营", "客户关系", "复购", "裂变"],
    "colors": "（品牌色请在 .env 或配置中指定）",
}


# ===== LangChain Tool 封装 =====

@tool
def load_template(template_type: str) -> str:
    """加载内容模板框架

    Args:
        template_type: 模板类型，可选：朋友圈文案/小红书笔记/活动方案/SOP文档/销售话术/企微推文/抖音脚本/社群公告

    Returns:
        模板结构说明和示例
    """
    template = CONTENT_TEMPLATES.get(template_type)
    if not template:
        available = "、".join(CONTENT_TEMPLATES.keys())
        return f"未找到「{template_type}」模板。可用模板：{available}"

    result = f"## {template_type} 模板框架\n\n"
    result += f"**结构**：{template['structure']}\n"
    result += f"**长度**：{template['length']}\n"
    result += f"**语气**：{template['tone']}\n"

    if template.get("example"):
        result += f"\n**参考示例**：\n{template['example']}\n"

    return result


@tool
def get_platform_rules(platform: str) -> str:
    """获取目标平台的内容规则和最佳实践

    Args:
        platform: 平台名称，可选：wecom/moments/xiaohongshu/douyin/web

    Returns:
        平台规则和最佳实践说明
    """
    rules = PLATFORM_RULES.get(platform)
    if not rules:
        available = "、".join(PLATFORM_RULES.keys())
        return f"未找到「{platform}」平台规则。可用平台：{available}"

    result = f"## {rules['name']} 平台规则\n\n"

    if rules.get("limits"):
        result += "**限制**：\n"
        for key, val in rules["limits"].items():
            result += f"  - {key}: {val}\n"

    if rules.get("features"):
        result += f"**支持功能**：{', '.join(rules['features'])}\n"

    if rules.get("best_practices"):
        result += "**最佳实践**：\n"
        for tip in rules["best_practices"]:
            result += f"  - {tip}\n"

    return result


@tool
def get_brand_guidelines() -> str:
    """获取品牌调性指南

    Returns:
        品牌调性要求和注意事项
    """
    result = "## 品牌调性指南\n\n"
    result += f"**语气风格**：{BRAND_GUIDELINES['tone']}\n\n"
    result += f"**避免内容**：{', '.join(BRAND_GUIDELINES['avoid'])}\n\n"
    result += f"**品牌关键词**：{', '.join(BRAND_GUIDELINES['keywords'])}\n\n"
    return result


@tool
def list_available_templates() -> str:
    """列出所有可用的内容模板类型

    Returns:
        可用模板列表
    """
    templates = []
    for name, info in CONTENT_TEMPLATES.items():
        templates.append(f"- **{name}**：{info['tone']}，{info['length']}")

    return "## 可用内容模板\n\n" + "\n".join(templates)
