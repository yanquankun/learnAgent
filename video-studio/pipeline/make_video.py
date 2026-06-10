"""一键流水线：脚本生成 → 配音 → 渲染，支持单章节或全量批量。

用法：
    # 单章节
    uv run python make_video.py "../../01-LLM基础/（一）认识LLM与第一次API调用"

    # 全部 36 个小节批量生成（已有 mp4 的自动跳过）
    uv run python make_video.py --all

    # 只重做某一步可单独运行 generate_script.py / generate_audio.py / build_video.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback

import build_video
import generate_audio
import generate_script
from common import Chapter, iter_all_chapters, load_env, resolve_chapter


def process(chapter: Chapter, voice: str, rate: str, force: bool) -> None:
    print(f"\n=== {chapter.slug} {chapter.chapter_title} ===")
    generate_script.run(chapter, force=force)
    asyncio.run(generate_audio.run(chapter, voice, rate, force))
    build_video.run(chapter)


def main() -> None:
    parser = argparse.ArgumentParser(description="README → 教学视频 一键流水线")
    parser.add_argument("chapter_dir", nargs="?", help="章节目录路径")
    parser.add_argument("--all", action="store_true", help="批量处理所有章节")
    parser.add_argument("--voice", default=generate_audio.DEFAULT_VOICE)
    parser.add_argument("--rate", default="+8%")
    parser.add_argument("--force", action="store_true", help="重新生成脚本与配音")
    args = parser.parse_args()

    load_env()

    if args.all:
        chapters = iter_all_chapters()
        todo = [c for c in chapters if force_or_missing(c, args.force)]
        print(f"共 {len(chapters)} 个小节，待生成 {len(todo)} 个（已有 mp4 的跳过）")
        failed: list[str] = []
        for chapter in todo:
            try:
                process(chapter, args.voice, args.rate, args.force)
            except Exception:
                traceback.print_exc()
                failed.append(f"{chapter.slug} {chapter.chapter_title}")
        if failed:
            print("\n以下章节失败，可单独重跑：")
            for f in failed:
                print(f"  - {f}")
            sys.exit(1)
    elif args.chapter_dir:
        process(resolve_chapter(args.chapter_dir), args.voice, args.rate, args.force)
    else:
        parser.error("请指定章节目录，或使用 --all 批量生成")


def force_or_missing(chapter: Chapter, force: bool) -> bool:
    return force or not chapter.output_mp4.is_file()


if __name__ == "__main__":
    main()
