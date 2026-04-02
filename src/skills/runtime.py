"""运行时 skill 文本加载工具。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent


def _skill_dir(skill_name: str) -> Path:
    return SKILLS_ROOT / skill_name


@cache
def read_skill_file(skill_name: str, relative_path: str = "SKILL.md") -> str:
    """读取单个 skill 文件。"""
    path = _skill_dir(skill_name) / relative_path
    return path.read_text(encoding="utf-8")


@cache
def build_skill_bundle(
    skill_names: tuple[str, ...],
    extra_files: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> str:
    """按 skill 组合构造可注入 prompt 的 markdown bundle。"""
    extra_map = dict(extra_files)
    sections: list[str] = []

    for skill_name in skill_names:
        sections.append(f"# Skill: {skill_name}\n" + read_skill_file(skill_name))
        for relative_path in extra_map.get(skill_name, ()):
            sections.append(
                f"# Reference: {skill_name}/{relative_path}\n"
                + read_skill_file(skill_name, relative_path)
            )

    return "\n\n".join(sections)
