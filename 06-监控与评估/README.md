# 模块 06：监控与评估

> 「没有评估集和指标，连这次改动是变好还是变坏都说不清。」本模块把 Agent 服务从「能跑」升级为「可观测、可评估、可回归」——这是 demo 和工程系统的真正分界线。

## 体系总览：五章五块拼图

```mermaid
flowchart TB
    subgraph obs ["可观测性（发生了什么）"]
        c1["（一）结构化日志 + qa_logs<br/>黑匣子：记录每次问答"]
        c2["（二）OpenTelemetry<br/>瀑布图：单次请求哪里慢"]
        c3["（三）Prometheus + Grafana<br/>仪表盘：服务整体如何"]
    end
    subgraph eval ["质量评估（答得好不好）"]
        c4["（四）Ragas<br/>LLM裁判：忠实度/相关性打分"]
        c5["（五）自建评估集<br/>回归红线：改动变好还是变坏"]
    end
    c1 --> c2 --> c3 --> c4 --> c5
```

## 章节导览

| 章节 | 核心内容 | 离线可跑 | 需要 Docker |
| --- | --- | --- | --- |
| （一）结构化日志与 qa_logs | JSON 日志、trace_id、问答落库与回放 | ✅ 全程 | — |
| （二）OpenTelemetry 链路追踪 | span 嵌套、属性、Jaeger 瀑布图 | ✅ 全程 | Jaeger（可选） |
| （三）Prometheus 与 Grafana | Counter/Histogram 埋点、/metrics、预配置看板 | ✅ 全程 | ✅ 监控栈 |
| （四）Ragas 入门（v0.4） | LLM as Judge、四大指标、自实现 Embedding 接口 | 需 LLM Key | — |
| （五）自建评估集与自动化回归 | hit@K/拒答正确率、markdown 报告、CI exit code | ✅ 全程 | — |

## 三个核心心法

1. **可观测性三件套各管一摊**：日志管「事件明细」、追踪管「单次请求的层级耗时」、指标管「服务整体趋势」——不是三选一，生产系统全要
2. **LLM 应用的特色指标**：token 消耗（成本）和检索空率/top_score（质量）必须从第一天就埋——这是普通 Web 服务没有的维度
3. **两层评估体系**：便宜的自建回归每次改动跑（秒级、零成本、确定），贵的 Ragas 里程碑跑（全面但有波动）——并且评估集的种子数据就来自第一章的 qa_logs

## 环境要求

- 二、三章用到本地 Docker（Jaeger / Prometheus / Grafana），compose 文件已备好，起停各一条命令
- 四章需要 LLM Key（DeepSeek 作裁判）；一、二、三、五章全程离线可跑

预计学习时间：6~8 小时（每章 1~1.5 小时）
