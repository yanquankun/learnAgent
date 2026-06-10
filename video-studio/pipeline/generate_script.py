"""第一步：把章节 README.md 提炼成视频解说脚本 scenes.json。

优先调用 DeepSeek（复用根目录 .env 的 LLM_API_KEY）生成口语化解说词；
没有配置 Key 时退化为「直接解析 README 结构」的离线模式（质量略低）。

用法：
    uv run python generate_script.py "../../01-LLM基础/（一）认识LLM与第一次API调用"
    uv run python generate_script.py <章节目录> --force   # 覆盖已有脚本
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from common import COURSE_TITLE, Chapter, load_env, resolve_chapter, write_scenes

SYSTEM_PROMPT = """你是一位资深技术课程的视频编导。把用户提供的教程章节 README（Markdown）改编成一支 3~6 分钟的中文教学视频脚本。

输出严格的 JSON 对象，结构如下：
{"scenes": [
  {"type": "title",   "heading": "章节主标题（不带（一）这类序号）", "bullets": ["一句话副标题"], "narration": "开场白"},
  {"type": "bullets", "heading": "小节标题", "bullets": ["要点1", "要点2"], "narration": "这一段的解说词"},
  {"type": "code",    "heading": "小节标题", "code": "代码内容", "codeLang": "python", "narration": "讲解这段代码的解说词"},
  {"type": "outro",   "heading": "本章小结", "bullets": ["收获1", "下一章预告"], "narration": "结束语"}
]}

硬性要求：
1. 共 8~12 个场景：第一个必须是 title，最后一个必须是 outro，中间按 README 的讲解顺序穿插 bullets 和 code 场景（code 场景 2~4 个）。
2. narration 是配音解说词：口语化、自然流畅，像老师讲课；每段 80~160 个汉字；禁止出现 Markdown 符号、英文标点的星号井号、emoji；英文术语可以保留（如 token、API）。
3. narration 必须覆盖该场景屏幕上的内容，并且与 bullets/code 一致，不能编造 README 里没有的事实。
4. bullets：每个场景最多 4 条，每条不超过 32 个字，是给观众看的提炼文字（可以保留少量行内代码词汇但不要加反引号）。
5. code：从 README 的代码块中节选最有代表性的片段，最多 12 行；保留原始缩进；不要 mermaid 图。
6. title 场景的 bullets 只放一句不超过 40 字的副标题；outro 场景的 bullets 放 2~4 条本章收获与下一章预告。
7. 只输出 JSON，不要任何解释文字。"""

VALID_TYPES = {"title", "bullets", "code", "outro"}


def _clean_narration(text: str) -> str:
    """去掉可能混入的 markdown 符号，保证 TTS 朗读干净。"""
    text = re.sub(r"[*#>`_~\[\]]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _validate(raw: dict) -> list[dict]:
    scenes = raw.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 3:
        raise ValueError(f"scenes 数量异常：{scenes if scenes is None else len(scenes)}")
    cleaned: list[dict] = []
    for s in scenes:
        stype = s.get("type")
        if stype not in VALID_TYPES:
            stype = "bullets"
        narration = _clean_narration(str(s.get("narration", "")))
        if not narration:
            continue
        scene = {
            "type": stype,
            "heading": str(s.get("heading", "")).strip() or "本节内容",
            "narration": narration,
        }
        if s.get("bullets"):
            scene["bullets"] = [str(b).strip() for b in s["bullets"] if str(b).strip()][:4]
        if stype == "code":
            code = str(s.get("code", "")).rstrip()
            if not code:
                scene["type"] = "bullets"
            else:
                scene["code"] = "\n".join(code.split("\n")[:14])
                scene["codeLang"] = str(s.get("codeLang", "python"))
        cleaned.append(scene)
    if cleaned[0]["type"] != "title":
        cleaned[0]["type"] = "title"
    if cleaned[-1]["type"] != "outro":
        cleaned[-1]["type"] = "outro"
    return cleaned


def _parse_json(content: str) -> dict:
    """解析模型返回的 JSON；遇到非法/截断 JSON（如 code 字段内嵌引号
    转义失败，常见于讲 JSON 本身的章节）时用 json_repair 容错修复。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        from json_repair import repair_json

        repaired = repair_json(content, return_objects=True)
        if not isinstance(repaired, dict) or not repaired.get("scenes"):
            raise ValueError("JSON 修复后仍无有效 scenes")
        print("  原始 JSON 非法，已用 json_repair 修复")
        return repaired


# ---------------------------------------------------------------------------
# 方式一：LLM 生成（推荐）
# ---------------------------------------------------------------------------

def generate_with_llm(readme_text: str) -> list[dict]:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
    )
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    print(f"  调用 {model} 生成解说脚本（约需 1~2 分钟）...")
    last_err: Exception | None = None
    # 模型偶发返回截断/非法 JSON，整体重试最多 3 次
    for attempt in range(3):
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": readme_text},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=8000,
        )
        content = response.choices[0].message.content or ""
        try:
            return _validate(_parse_json(content))
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f"  第 {attempt + 1} 次解析失败（{e}），重试...")
    raise RuntimeError(f"LLM 脚本生成连续失败：{last_err}")


# ---------------------------------------------------------------------------
# 方式二：离线解析 README（无 LLM Key 时的兜底）
# ---------------------------------------------------------------------------

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_INLINE = re.compile(r"[*_`>#]+")


def _strip_md(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_INLINE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def generate_offline(readme_text: str, chapter: Chapter) -> list[dict]:
    print("  未配置 LLM_API_KEY，使用离线模式解析 README（解说词为原文节选）...")
    lines = readme_text.split("\n")

    # 按 ## 切分章节
    sections: list[dict] = []
    current: dict | None = None
    intro_quote = ""
    in_code = False
    code_lang = ""
    code_lines: list[str] = []

    for line in lines:
        if line.startswith("```"):
            if in_code:
                in_code = False
                if current is not None and code_lang not in ("mermaid", ""):
                    current.setdefault("codes", []).append(
                        ("\n".join(code_lines[:14]), code_lang)
                    )
                code_lines = []
            else:
                in_code = True
                code_lang = line.strip("`").strip()
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("## "):
            current = {"heading": _strip_md(line[3:]), "paras": [], "bullets": []}
            sections.append(current)
            continue
        if line.startswith("> ") and current is None:
            intro_quote = _strip_md(line[2:])
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")) or re.match(r"^\d+\. ", stripped):
            text = _strip_md(re.sub(r"^(- |\* |\d+\. )", "", stripped))
            if text:
                current["bullets"].append(text)
        elif stripped and not stripped.startswith("|"):
            text = _strip_md(stripped)
            if text:
                current["paras"].append(text)

    scenes: list[dict] = [{
        "type": "title",
        "heading": chapter.clean_title,
        "bullets": [intro_quote[:40] or f"{chapter.module_name} 系列课程"],
        "narration": f"大家好，欢迎来到 {chapter.module_name} 模块。这一节我们学习，"
                     f"{chapter.clean_title}。{intro_quote}",
    }]

    for sec in sections:
        if any(k in sec["heading"] for k in ("延伸阅读", "官方文档", "下一章")):
            continue
        narration = "。".join(sec["paras"][:3])[:160] or "。".join(sec["bullets"][:3])[:160]
        if not narration:
            continue
        scenes.append({
            "type": "bullets",
            "heading": sec["heading"][:30],
            "bullets": [b[:32] for b in sec["bullets"][:4]] or [p[:32] for p in sec["paras"][:3]],
            "narration": narration,
        })
        for code, lang in sec.get("codes", [])[:1]:
            scenes.append({
                "type": "code",
                "heading": sec["heading"][:30],
                "code": code,
                "codeLang": lang or "python",
                "narration": f"我们来看一段代码。{sec['paras'][0][:80] if sec['paras'] else ''}",
            })

    next_preview = ""
    for sec in sections:
        if "下一章" in sec["heading"] and sec["paras"]:
            next_preview = sec["paras"][0][:60]
    scenes.append({
        "type": "outro",
        "heading": "本章小结",
        "bullets": [f"动手完成 {chapter.clean_title} 的实践", next_preview or "我们下一章见"],
        "narration": f"以上就是本章的全部内容。{next_preview} 我们下一章见。",
    })
    return _validate({"scenes": scenes[:12]})


# ---------------------------------------------------------------------------

def run(chapter: Chapter, force: bool = False) -> None:
    if chapter.scenes_json.is_file() and not force:
        print(f"  已存在 {chapter.scenes_json}，跳过（--force 可覆盖）")
        return
    readme_text = chapter.readme.read_text(encoding="utf-8")

    if os.environ.get("LLM_API_KEY", "").strip():
        scenes = generate_with_llm(readme_text)
    else:
        scenes = generate_offline(readme_text, chapter)

    data = {
        "slug": chapter.slug,
        "courseTitle": COURSE_TITLE,
        "moduleTitle": chapter.module_name,
        "chapterTitle": chapter.chapter_title,
        "scenes": scenes,
    }
    write_scenes(chapter, data)
    print(f"  已生成 {len(scenes)} 个场景 → {chapter.scenes_json}")


def main() -> None:
    parser = argparse.ArgumentParser(description="README → 视频解说脚本 scenes.json")
    parser.add_argument("chapter_dir", help="章节目录路径")
    parser.add_argument("--force", action="store_true", help="覆盖已有 scenes.json")
    args = parser.parse_args()

    load_env()
    chapter = resolve_chapter(args.chapter_dir)
    print(f"[generate_script] {chapter.slug} {chapter.chapter_title}")
    run(chapter, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
