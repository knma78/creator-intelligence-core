from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


NOVEL_WRITING_CAPABILITIES = (
    "故事契约与题材定位",
    "长篇结构与篇章阶梯",
    "场景转折与章节钩子",
    "成长系统与回报节奏",
    "世界观规则与代价",
    "人物弧光与关系推进",
    "对白潜台词",
    "悬念与信息差",
    "情绪连续性",
    "诊断、改写与修订",
    "中文与母语级美式/英式英语创作",
    "本地小说语料指标分析",
)
ENGLISH_REVIEW_CAPABILITIES = (
    "英语母语自然度审查",
    "美式与英式英语一致性",
    "英文对白真实性",
    "文化概念可理解性",
    "有声书朗读清晰度",
    "中国网文机制保留检查",
    "中文可解释问题报告",
)


@dataclass(frozen=True)
class LocalSkill:
    name: str
    description: str
    root: Path
    instructions: str
    references: dict[str, str]
    scripts: tuple[Path, ...]
    fingerprint: str
    capabilities: tuple[str, ...]

    def status(self) -> dict[str, Any]:
        files = [self.root / "SKILL.md", *self.scripts]
        files.extend(self.root / "references" / name for name in self.references)
        latest_mtime = max(path.stat().st_mtime for path in files if path.is_file())
        return {
            "name": self.name,
            "description": self.description,
            "available": True,
            "path": str(self.root),
            "fingerprint": self.fingerprint,
            "updated_at": datetime.fromtimestamp(
                latest_mtime,
                tz=timezone.utc,
            ).isoformat(),
            "references": sorted(self.references),
            "scripts": [path.name for path in self.scripts],
            "capabilities": list(self.capabilities),
        }


def load_novel_writing_skill(
    root: Path,
    *,
    include_corpus_observations: bool = False,
) -> LocalSkill:
    root = Path(root).expanduser().resolve()
    skill_path = root / "SKILL.md"
    if not skill_path.is_file():
        raise FileNotFoundError(f"找不到 novel-writing Skill：{skill_path}")

    raw = skill_path.read_text(encoding="utf-8")
    metadata, instructions = _split_frontmatter(raw)
    declared_name = str(metadata.get("name") or "").strip()
    if declared_name and declared_name != "novel-writing":
        raise ValueError(
            f"Skill 名称应为 novel-writing，实际为 {declared_name}。"
        )

    reference_names = ["craft-patterns.md"]
    if include_corpus_observations:
        reference_names.append("corpus-observations.md")
    references: dict[str, str] = {}
    for name in reference_names:
        path = root / "references" / name
        if not path.is_file():
            raise FileNotFoundError(f"Skill 缺少参考文件：{path}")
        references[name] = path.read_text(encoding="utf-8")

    scripts_dir = root / "scripts"
    scripts = tuple(sorted(scripts_dir.glob("*.py"))) if scripts_dir.is_dir() else ()
    fingerprint = _fingerprint(
        [skill_path]
        + [root / "references" / name for name in references]
        + list(scripts)
    )
    return LocalSkill(
        name=declared_name or "novel-writing",
        description=str(metadata.get("description") or "").strip(),
        root=root,
        instructions=instructions.strip(),
        references=references,
        scripts=scripts,
        fingerprint=fingerprint,
        capabilities=NOVEL_WRITING_CAPABILITIES,
    )


def load_native_english_review_skill(root: Path) -> LocalSkill:
    root = Path(root).expanduser().resolve()
    skill_path = root / "SKILL.md"
    rubric_path = root / "references" / "review-rubric.md"
    if not skill_path.is_file():
        raise FileNotFoundError(
            f"找不到 native-english-fiction-review Skill：{skill_path}"
        )
    if not rubric_path.is_file():
        raise FileNotFoundError(f"英语审稿 Skill 缺少评分表：{rubric_path}")
    raw = skill_path.read_text(encoding="utf-8")
    metadata, instructions = _split_frontmatter(raw)
    declared_name = str(metadata.get("name") or "").strip()
    if declared_name and declared_name != "native-english-fiction-review":
        raise ValueError(
            "Skill 名称应为 native-english-fiction-review，"
            f"实际为 {declared_name}。"
        )
    references = {"review-rubric.md": rubric_path.read_text(encoding="utf-8")}
    scripts_dir = root / "scripts"
    scripts = tuple(sorted(scripts_dir.glob("*.py"))) if scripts_dir.is_dir() else ()
    fingerprint = _fingerprint([skill_path, rubric_path, *scripts])
    return LocalSkill(
        name=declared_name or "native-english-fiction-review",
        description=str(metadata.get("description") or "").strip(),
        root=root,
        instructions=instructions.strip(),
        references=references,
        scripts=scripts,
        fingerprint=fingerprint,
        capabilities=ENGLISH_REVIEW_CAPABILITIES,
    )


def get_novel_writing_skill_status(root: Path) -> dict[str, Any]:
    try:
        return load_novel_writing_skill(root).status()
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "name": "novel-writing",
            "available": False,
            "path": str(Path(root).expanduser()),
            "reason": str(exc),
            "capabilities": list(NOVEL_WRITING_CAPABILITIES),
        }


def get_native_english_review_skill_status(root: Path) -> dict[str, Any]:
    try:
        return load_native_english_review_skill(root).status()
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "name": "native-english-fiction-review",
            "available": False,
            "path": str(Path(root).expanduser()),
            "reason": str(exc),
            "capabilities": list(ENGLISH_REVIEW_CAPABILITIES),
        }


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    normalized = text.lstrip("\ufeff")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, normalized
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError("SKILL.md 的 YAML frontmatter 未闭合。") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    return metadata, "\n".join(lines[end + 1 :])


def _fingerprint(paths: list[Path]) -> str:
    digest = sha256()
    for path in sorted(paths, key=lambda item: str(item).lower()):
        digest.update(str(path.name).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
