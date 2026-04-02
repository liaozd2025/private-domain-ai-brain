"""Agent Skills 元数据规范测试。"""

from __future__ import annotations

from pathlib import Path

import yaml


def _read_frontmatter(skill_md: Path) -> dict[str, str]:
    content = skill_md.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines and lines[0].strip() == "---", f"{skill_md} 缺少 frontmatter 起始标记"

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break

    assert closing_index is not None, f"{skill_md} 缺少 frontmatter 结束标记"
    frontmatter = "\n".join(lines[1:closing_index]).strip()
    assert frontmatter, f"{skill_md} frontmatter 不能为空"
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict), f"{skill_md} frontmatter 必须是 YAML 对象"
    return data


def test_all_skill_docs_follow_agent_skills_frontmatter_spec():
    """所有 SKILL.md 都应符合 Deep Agents / Agent Skills 的最小元数据要求。"""
    skills_root = Path(__file__).resolve().parents[1] / "src" / "skills"
    skill_docs = sorted(skills_root.glob("*/SKILL.md"))

    assert skill_docs, "未找到任何 SKILL.md"

    for skill_md in skill_docs:
        metadata = _read_frontmatter(skill_md)
        skill_dir_name = skill_md.parent.name

        assert metadata.get("name") == skill_dir_name
        description = metadata.get("description")
        assert isinstance(description, str) and description.strip()
