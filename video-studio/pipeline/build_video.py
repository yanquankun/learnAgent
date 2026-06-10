"""第三步：调用 Remotion 渲染，把 mp4 输出到章节目录。

用法：
    uv run python build_video.py "../../01-LLM基础/（一）认识LLM与第一次API调用"
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from common import STUDIO_DIR, Chapter, load_env, read_scenes, resolve_chapter


def run(chapter: Chapter) -> None:
    data = read_scenes(chapter)
    missing = [i for i, s in enumerate(data["scenes"], 1) if not s.get("durationInFrames")]
    if missing:
        raise SystemExit(f"场景 {missing} 缺少时长信息，请先运行 generate_audio.py")

    out = chapter.output_mp4
    print(f"  开始渲染 → {out}")
    cmd = [
        "npx", "remotion", "render", "ChapterVideo",
        str(out),
        f"--props={chapter.scenes_json}",
        "--codec=h264",
    ]
    result = subprocess.run(cmd, cwd=STUDIO_DIR)
    if result.returncode != 0:
        raise SystemExit(f"Remotion 渲染失败（exit={result.returncode}）")
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"  渲染完成：{out.name}（{size_mb:.1f} MB）")


def main() -> None:
    parser = argparse.ArgumentParser(description="scenes.json → Remotion 渲染 mp4")
    parser.add_argument("chapter_dir", help="章节目录路径")
    args = parser.parse_args()

    load_env()
    chapter = resolve_chapter(args.chapter_dir)
    print(f"[build_video] {chapter.slug} {chapter.chapter_title}")
    run(chapter)


if __name__ == "__main__":
    sys.exit(main())
