"""
traffic.py —— 模拟流量脚本

往本地服务打 90 秒随机流量，让 Prometheus 抓到足够数据、
Grafana 画出能看的曲线。

用法（先把服务跑起来）：
    终端1：uv run uvicorn app:app --port 8000
    终端2：uv run python traffic.py
"""

import random
import time

import httpx

QUESTIONS = [
    "useEffect 为什么执行两次",
    "怎么部署 Postgres",
    "事件循环是什么",
    "Vite 比 webpack 快在哪",
    "向量数据库怎么选",
]

DURATION_SECONDS = 90

if __name__ == "__main__":
    client = httpx.Client(base_url="http://localhost:8000", timeout=10)
    deadline = time.time() + DURATION_SECONDS
    count = 0
    print(f"开始打流量，持续 {DURATION_SECONDS} 秒……（Ctrl+C 可提前停止）")
    while time.time() < deadline:
        try:
            client.get("/api/chat", params={"q": random.choice(QUESTIONS)})
            count += 1
            if count % 20 == 0:
                print(f"  已发送 {count} 个请求")
        except httpx.HTTPError as exc:
            print(f"  请求失败：{exc}（服务没启动？）")
            time.sleep(2)
        # 随机间隔，让 QPS 曲线有起伏（更接近真实流量）
        time.sleep(random.uniform(0.05, 0.5))
    print(f"完成，共发送 {count} 个请求。去 Grafana 看曲线吧！")
