"""第二步：为 scenes.json 的每个场景生成 edge-tts 中文配音，并写回时长。

音频输出到 video-studio/public/audio/<slug>/，Remotion 组件用 staticFile() 引用。

用法：
    uv run python generate_audio.py "../../01-LLM基础/（一）认识LLM与第一次API调用"
    uv run python generate_audio.py <章节目录> --voice zh-CN-YunxiNeural --force
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys

import edge_tts
from mutagen.mp3 import MP3

from common import FPS, Chapter, load_env, read_scenes, resolve_chapter, write_scenes

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"  # 微软晓晓，自然的中文女声
# 每段解说结束后留一点呼吸感，画面不至于立刻切走
TAIL_PADDING_SECONDS = 0.7
MIN_SCENE_FRAMES = 90


async def synth_one(text: str, voice: str, rate: str, out_path) -> None:
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(out_path))


async def run(chapter: Chapter, voice: str, rate: str, force: bool) -> None:
    data = read_scenes(chapter)
    chapter.audio_dir.mkdir(parents=True, exist_ok=True)

    for i, scene in enumerate(data["scenes"], start=1):
        rel_path = f"audio/{chapter.slug}/scene-{i:03d}.mp3"
        out_path = chapter.audio_dir / f"scene-{i:03d}.mp3"

        if out_path.is_file() and scene.get("audioFile") and not force:
            print(f"  [{i:02d}] 已存在，跳过")
        else:
            narration = scene["narration"]
            print(f"  [{i:02d}] 合成配音（{len(narration)} 字）: {narration[:24]}...")
            # edge-tts 偶发网络抖动，重试 3 次
            for attempt in range(3):
                try:
                    await synth_one(narration, voice, rate, out_path)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"       第 {attempt + 1} 次失败（{e}），重试...")
                    await asyncio.sleep(2 * (attempt + 1))

        duration_sec = MP3(out_path).info.length
        frames = max(MIN_SCENE_FRAMES, math.ceil((duration_sec + TAIL_PADDING_SECONDS) * FPS))
        scene["audioFile"] = rel_path
        scene["durationInFrames"] = frames

    write_scenes(chapter, data)
    total_frames = sum(s["durationInFrames"] for s in data["scenes"])
    print(f"  完成：{len(data['scenes'])} 段配音，总时长约 {total_frames / FPS:.0f} 秒")


def main() -> None:
    parser = argparse.ArgumentParser(description="scenes.json → edge-tts 配音")
    parser.add_argument("chapter_dir", help="章节目录路径")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"音色（默认 {DEFAULT_VOICE}）")
    parser.add_argument("--rate", default="+8%", help="语速调整（默认 +8%%，稍快更像讲课）")
    parser.add_argument("--force", action="store_true", help="重新合成已有音频")
    args = parser.parse_args()

    load_env()
    chapter = resolve_chapter(args.chapter_dir)
    print(f"[generate_audio] {chapter.slug} {chapter.chapter_title}（voice={args.voice}）")
    asyncio.run(run(chapter, args.voice, args.rate, args.force))


if __name__ == "__main__":
    sys.exit(main())
