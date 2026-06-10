"""流水线公共工具：路径解析、章节信息提取、scenes.json 读写。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PIPELINE_DIR = Path(__file__).resolve().parent
STUDIO_DIR = PIPELINE_DIR.parent
REPO_ROOT = STUDIO_DIR.parent
DATA_DIR = STUDIO_DIR / "data"
PUBLIC_DIR = STUDIO_DIR / "public"

COURSE_TITLE = "learnAgent"
FPS = 30

# 中文序号 → 数字（章节目录形如「（一）认识LLM与第一次API调用」）
_CN_NUM = {c: i + 1 for i, c in enumerate("一二三四五六七八九")}
_CN_NUM["十"] = 10

_CHAPTER_RE = re.compile(r"^（(.+?)）(.+)$")
_MODULE_RE = re.compile(r"^(\d{2})-(.+)$")


def load_env() -> None:
    """加载仓库根目录的全局 .env（与各章节 project 的约定一致）。"""
    load_dotenv(REPO_ROOT / ".env")


@dataclass
class Chapter:
    """一个小节的全部路径与元信息。"""

    chapter_dir: Path     # 如 .../01-LLM基础/（一）认识LLM与第一次API调用
    module_name: str      # 01-LLM基础
    module_num: str       # 01
    chapter_num: int      # 1
    chapter_title: str    # （一）认识LLM与第一次API调用
    clean_title: str      # 认识LLM与第一次API调用（用作 mp4 文件名）
    slug: str             # 01-01

    @property
    def readme(self) -> Path:
        return self.chapter_dir / "README.md"

    @property
    def scenes_json(self) -> Path:
        return DATA_DIR / self.slug / "scenes.json"

    @property
    def audio_dir(self) -> Path:
        """音频放在 Remotion 的 public/ 下，组件里用 staticFile() 引用。"""
        return PUBLIC_DIR / "audio" / self.slug

    @property
    def output_mp4(self) -> Path:
        return self.chapter_dir / f"{self.clean_title}.mp4"


def resolve_chapter(path_str: str) -> Chapter:
    """从章节目录路径解析出 Chapter 信息。"""
    chapter_dir = Path(path_str).expanduser().resolve()
    if not chapter_dir.is_dir():
        raise SystemExit(f"目录不存在：{chapter_dir}")
    if not (chapter_dir / "README.md").is_file():
        raise SystemExit(f"目录下没有 README.md：{chapter_dir}")

    chapter_name = chapter_dir.name
    m_chapter = _CHAPTER_RE.match(chapter_name)
    if not m_chapter:
        raise SystemExit(f"章节目录名不符合「（一）标题」格式：{chapter_name}")
    ordinal_text, clean_title = m_chapter.group(1), m_chapter.group(2)
    chapter_num = _CN_NUM.get(ordinal_text)
    if chapter_num is None:
        raise SystemExit(f"无法识别章节序号：{ordinal_text}")

    module_name = chapter_dir.parent.name
    m_module = _MODULE_RE.match(module_name)
    if not m_module:
        raise SystemExit(f"模块目录名不符合「01-名称」格式：{module_name}")

    return Chapter(
        chapter_dir=chapter_dir,
        module_name=module_name,
        module_num=m_module.group(1),
        chapter_num=chapter_num,
        chapter_title=chapter_name,
        clean_title=clean_title,
        slug=f"{m_module.group(1)}-{chapter_num:02d}",
    )


def iter_all_chapters() -> list[Chapter]:
    """遍历仓库所有「NN-模块/（X）章节」目录。"""
    chapters: list[Chapter] = []
    for module_dir in sorted(REPO_ROOT.iterdir()):
        if not module_dir.is_dir() or not _MODULE_RE.match(module_dir.name):
            continue
        for chapter_dir in sorted(module_dir.iterdir()):
            if (
                chapter_dir.is_dir()
                and _CHAPTER_RE.match(chapter_dir.name)
                and (chapter_dir / "README.md").is_file()
            ):
                chapters.append(resolve_chapter(str(chapter_dir)))
    return chapters


def read_scenes(chapter: Chapter) -> dict:
    if not chapter.scenes_json.is_file():
        raise SystemExit(
            f"找不到 {chapter.scenes_json}，请先运行 generate_script.py"
        )
    return json.loads(chapter.scenes_json.read_text(encoding="utf-8"))


def write_scenes(chapter: Chapter, data: dict) -> None:
    chapter.scenes_json.parent.mkdir(parents=True, exist_ok=True)
    chapter.scenes_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
