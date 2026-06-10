"""
simulate_webhook.py —— 本地模拟 GitHub Webhook 的测试脚本

没有公网地址也能完整测试动态 RAG：脚本会真实地修改 mock_repo/ 里的
文件，然后构造与 GitHub 一致的 push 事件 payload（含正确签名）发给
本地服务 —— 服务的处理逻辑与收到真实 GitHub 事件完全一样。

用法（先把服务跑起来：uv run uvicorn app:app --port 8000）：
    uv run python scripts/simulate_webhook.py add       # 新增一篇文章
    uv run python scripts/simulate_webhook.py modify    # 修改一篇文章
    uv run python scripts/simulate_webhook.py remove    # 删除新增的那篇
    uv run python scripts/simulate_webhook.py bad-sig   # 伪造签名（应被 403 拒绝）
    uv run python scripts/simulate_webhook.py restore   # 还原 mock_repo
"""

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

SERVER = "http://localhost:8000"
REPO_DIR = config.LOCAL_REPO_DIR
NEW_POST = REPO_DIR / "posts" / "fastapi-sse.md"
MODIFY_POST = REPO_DIR / "posts" / "vite-migration.md"

NEW_POST_CONTENT = """---
title: 用 FastAPI 实现 SSE 流式接口
tags: [fastapi, sse, python]
---

## 为什么聊天接口要用 SSE

LLM 生成一段回答需要几秒甚至十几秒，一次性返回的话用户会盯着空屏幕干等。
SSE（Server-Sent Events）让服务端把回答一小段一小段推给浏览器，实现打字机效果。

## FastAPI 的实现要点

用 StreamingResponse 包一个生成器，media_type 设为 text/event-stream。
每条消息的格式是 data: 开头加两个换行结尾。记得加 X-Accel-Buffering: no
响应头，否则 Nginx 反代会把流缓冲成一整块。
"""


def sign(body: bytes) -> str:
    """与 GitHub 相同的签名算法：sha256= + HMAC-SHA256(secret, body)。"""
    return "sha256=" + hmac.new(config.WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def send_push(added: list[str], modified: list[str], removed: list[str], fake_sig: bool = False) -> None:
    """构造 push 事件并发送（结构与真实 GitHub payload 的关键字段一致）。"""
    payload = {
        "ref": "refs/heads/main",
        "commits": [
            {"id": f"sim{int(time.time())}", "added": added, "modified": modified, "removed": removed}
        ],
    }
    body = json.dumps(payload).encode()
    signature = "sha256=deadbeef" if fake_sig else sign(body)

    try:
        resp = httpx.post(
            f"{SERVER}/api/github/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": signature,
            },
            timeout=10,
        )
    except httpx.ConnectError:
        print(f"连不上 {SERVER} —— 请先启动服务：uv run uvicorn app:app --port 8000")
        sys.exit(1)
    print(f"HTTP {resp.status_code}: {resp.text}")


def main() -> None:
    if not config.WEBHOOK_SECRET:
        print("请先在根目录 .env 配置 WEBHOOK_SECRET（随便一串随机字符串）")
        sys.exit(1)

    scenario = sys.argv[1] if len(sys.argv) > 1 else "add"

    if scenario == "add":
        NEW_POST.write_text(NEW_POST_CONTENT, encoding="utf-8")
        print(f"已写入新文章：{NEW_POST.name}，发送 push 事件……")
        send_push(added=[f"posts/{NEW_POST.name}"], modified=[], removed=[])
        print("验证：稍等几秒后问服务「SSE 是什么」，应该能答上来了！")

    elif scenario == "modify":
        text = MODIFY_POST.read_text(encoding="utf-8")
        MODIFY_POST.write_text(text + f"\n\n（{time.strftime('%H:%M:%S')} 补充：迁移后记得删除 webpack 依赖。）\n", encoding="utf-8")
        print(f"已修改：{MODIFY_POST.name}，发送 push 事件……")
        send_push(added=[], modified=[f"posts/{MODIFY_POST.name}"], removed=[])

    elif scenario == "remove":
        if NEW_POST.exists():
            NEW_POST.unlink()
        print(f"已删除：{NEW_POST.name}，发送 push 事件……")
        send_push(added=[], modified=[], removed=[f"posts/{NEW_POST.name}"])
        print("验证：GET /api/index/jobs 应有一条 deleted 记录；再问 SSE 会被拒答。")

    elif scenario == "bad-sig":
        print("用伪造签名发送（服务应返回 403）……")
        send_push(added=["posts/hack.md"], modified=[], removed=[], fake_sig=True)

    elif scenario == "restore":
        if NEW_POST.exists():
            NEW_POST.unlink()
        text = MODIFY_POST.read_text(encoding="utf-8")
        idx = text.find("\n\n（")
        if idx != -1:
            MODIFY_POST.write_text(text[:idx] + "\n", encoding="utf-8")
        print("mock_repo 已还原（向量库请用 index_cli.py --rebuild 重建）")

    else:
        print(f"未知场景：{scenario}（可选 add / modify / remove / bad-sig / restore）")


if __name__ == "__main__":
    main()
