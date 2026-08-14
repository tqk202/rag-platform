# rag-platform · 企业知识库 RAG 问答平台

> 一个面向真实企业场景的检索增强生成（RAG）问答系统。用于求职作品集，突出**工程化落地能力**：多租户权限、文档生命周期、异步文档处理、全链路可观测、评测体系。

## 为什么不是 demo

面试官看 RAG 项目只关心七个问题，本项目的设计逐条对应：

| 面试官会问 | 本项目怎么答 |
|---|---|
| 回答质量怎么度量？ | 评测体系：黄金评测集 + RAGAS 指标 + 消融实验 |
| 多部门数据权限怎么隔离？ | 多租户 + 文档级/片段级权限（元数据过滤） |
| 文档更新/删除会过时吗？ | 重传升版（版本号 +1）+ 旧切片双存储同步清理 |
| 没有答案的问题怎么处理？ | 无答案识别 |
| 怎么防止胡编、让用户信服？ | 引文/来源标注 |
| 线上坏回答怎么定位？ | 全链路追踪（Langfuse/OpenTelemetry） |
| 参数选择凭什么？ | 系统性消融实验 + 回归评测 |

## 技术栈

| 层 | 选型 |
|---|---|
| LLM | DeepSeek / Qwen（OpenAI 兼容，多 Provider 抽象） |
| Embedding / Rerank | bge-m3 / bge-reranker-v2 |
| 向量库 | Milvus（元数据过滤做权限） |
| 元数据库 | PostgreSQL 16 |
| 后端 | FastAPI + SQLAlchemy 2 (async) + Celery |
| 前端 | Vue3 + TypeScript + Element Plus + Vite |
| 可观测 | Langfuse（可选） |
| 部署 | Docker Compose |

## 快速启动

```bash
# 1. 准备环境变量
cp .env.example .env

# 2. 一键拉起全部服务（Postgres/Redis/Milvus/后端/Worker/前端）
docker compose up --build

# 3. 访问
# 前端: http://localhost:5173
# 后端 API 文档: http://localhost:8000/docs
# MinIO 控制台: http://localhost:9001 (minioadmin/minioadmin)
```

## 轻量开发模式（无需 Docker，Windows 友好）

用 SQLite + Milvus Lite（本地文件）+ inline 处理，秒级启动，先跑通再切正式环境：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements-dev.txt
# backend/.env 已配置轻量模式
uvicorn app.main:app --reload
```

> 两种模式通过环境变量切换：`DATABASE_URL`（sqlite+aiosqlite / postgresql+asyncpg）、
> `VECTOR_URI`（Milvus 本地文件 / http 地址）、`INGESTION_MODE`（inline / async）。
> 这是真实项目常见的"开发/生产配置分离"。

## 评测体系（W4）

回答质量用数字说话，不靠感觉：

```bash
cd backend
.venv\Scripts\python scripts/ablation.py             # mock 模式（免费，验证流程）
.venv\Scripts\python scripts/ablation.py api         # 真实 LLM 裁判（花少量 API 费用）
.venv\Scripts\python scripts/ablation.py api real    # 全真实：bge-m3 嵌入 + bge-reranker 重排 + DeepSeek 裁判
```

- **黄金评测集**：`backend/eval_data/golden_set.json`，18 道「问题 + 标准答案出处」，基于演示文档手写。
- **四个指标**：`context_precision` / `context_recall`（检索质量，用黄金答案出处算）+ `faithfulness` / `answer_relevancy`（生成质量，LLM 当裁判）。手写 RAGAS 风格实现，便于讲清原理。
- **消融实验**：每个配置跑在独立子进程里控制变量，对比「纯向量 vs 混合」「有重排 vs 无重排」「chunk 500 vs 300」。
- 评测用**独立库**（`data/eval_rag.db` + `data/eval_milvus.db`），不污染开发数据。报告输出到 `backend/eval_reports/`。

**实测（全真实模式，18 题）**——嵌入 bge-m3 + 重排 bge-reranker-v2-m3（SiliconFlow）+ 裁判 DeepSeek：

| 配置 | context_precision | context_recall | faithfulness | answer_relevancy |
|---|---|---|---|---|
| 混合检索+重排 (chunk500) | 1.0 | 1.0 | 1.0 | 1.0 |
| 纯向量检索 (chunk500) | 0.9444 | 1.0 | 1.0 | 1.0 |
| 混合检索 无重排 (chunk500) | 0.9444 | 1.0 | 1.0 | 1.0 |
| 混合检索+重排 (chunk300) | 1.0 | 1.0 | 1.0 | 1.0 |

要点：mock 哈希嵌入下纯向量只有 0.21（无语义），换真实 bge-m3 后 **0.21 → 0.94**——语义嵌入的价值被直接量化；真实重排把无重排漏掉的 2 道题（0.5）修正到满分。全 1.0 是**小语料天花板**（5 份文档、18 题全覆盖），更大语料才能拉开配置差距。

## 工程规范（W5）

线上坏回答怎么定位、花钱的接口怎么防刷、代码质量怎么守门：

- **可观测性**：纯 ASGI 中间件给每个请求发 `request_id`（响应头 `X-Request-ID` 回传），
  通过 contextvars + `setLogRecordFactory` 让整条链的日志都带 rid——
  拿一个坏回答的 id 就能把这条链（鉴权→检索→LLM→响应）捞出来。SSE 流式不受影响。
- **限流**：手写令牌桶（token bucket）保护 `/chat`（每次都是真实 LLM 调用）。
  每用户独立桶，超限返回 `429` + `Retry-After`。生产可换 Redis 分布式限流。
- **CI**：`.github/workflows/ci.yml`，push/PR 自动跑 `pytest` + `ruff`。
  测试用独立库（SQLite + Milvus Lite），无需外部服务，runner 直接能跑。
- **静态检查**：`backend/ruff.toml`，规则刻意挑过并注释了为什么（中文全角标点、
  HTTP 状态码、惰性 import 等合理的写法都显式放行）。

```bash
# 本地跑一遍 CI 会做的事
cd backend
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check app scripts tests
```

## 边界打磨（W6）

线上会出什么问题、怎么防——异常输入和不稳定依赖都不能把系统打穿：

- **外部依赖兜底**：全局分层异常处理。LLM/向量库挂了或超时 → 返回 `502` 统一 JSON
  （`UPSTREAM_ERROR` / `UPSTREAM_UNAVAILABLE`），未捕获异常 → `500` 统一 JSON。
  真实堆栈进日志、用户只看到友好提示，不再裸 `500`。
- **上传安全边界**：类型白名单（只收 `.txt/.md/.pdf/.doc/.docx`）+ 大小上限（20MB，
  **分块读取**防超大文件撑爆内存）+ 空文件拒绝。OWASP 文件上传安全三件套。
- **API 层输入校验**：`/chat` 空问题/纯空格直接 `422`——API 是最后一道闸，
  不能只信前端，省下每次白烧的 LLM 调用。
- **7 个边界测试**（`tests/test_edge_cases.py`）：坏扩展名 / 空文件 / 超大小 /
  空问题 / LLM 挂了 502 / SSE 错误事件 / 正常路径回归，全量 29 测试通过。

## 文档版本管理（W6）

文档改了怎么办？同部门**重新上传同名文件**就是一次版本更新，不用删旧建新：

- 版本号自动 +1（列表接口和前端表格直接展示当前版本）。
- 旧切片**先清后灌**：Milvus 向量 + 数据库记录同步清掉再灌新内容，不会新旧数据混库。
- 相同内容重传直接拒绝（"已是最新版本"），不白处理一遍。
- 处理中的文档拒绝再次更新，避免异步模式下新旧处理任务抢数据。
- 3 个版本测试（`tests/test_versioning.py`）验证：升版、旧切片清理、同内容拒绝。

## 目录结构

```
├── docker-compose.yml      # 一键启动全部依赖
├── backend/
│   ├── app/
│   │   ├── api/            # 路由层（认证/文档/问答）
│   │   ├── services/       # 业务逻辑（文档/检索/问答/向量）
│   │   ├── models/         # 数据库模型
│   │   ├── schemas/        # API 请求/响应定义
│   │   ├── core/           # 配置、安全、异常
│   │   └── tasks/          # Celery 异步任务
│   └── tests/              # 测试
├── frontend/
│   └── src/                # Vue3 前端
└── docs/
    └── architecture.md     # 架构说明
```

## 路线图

- [x] W1 骨架与文档管线：上传 → 解析 → 切片 → 向量化 → 入库
- [x] W2 检索与问答：混合检索（BM25+向量+RRF）+ RAG 问答 + 引文标注（当前 Mock LLM，可切 API）
- [x] W2.5a 真实 LLM 接入：OpenAI 兼容客户端（DeepSeek），提炼式回答 + 引文 + no_answer 哨兵句
- [x] W2.5b 流式输出：SSE 逐字推送（meta/delta/done 事件）+ 前端打字机效果
- [x] W2.5c Rerank 重排：召回(20)→重排→取前5→生成三层管线（RerankerProvider 接口抽象 + 真实 bge-reranker-v2-m3，词法实现保留作离线对照）
- [x] W3 多租户权限：RBAC 角色门卫 + 检索层元数据过滤 + 越权测试（含删除清向量）
- [x] W4 评测体系：黄金评测集（18 题）+ RAGAS 风格四指标 + 消融实验（纯向量/混合/重排/chunk 大小）
- [x] W5 工程规范：request_id 全链路追踪 + 令牌桶限流 + GitHub Actions CI
- [x] W6 边界打磨：外部依赖兜底 + 上传安全边界 + 输入校验
- [x] W6 版本管理：同文件名重传升版 + 旧切片双存储同步清理
- [x] W6 切真实模型：bge-m3 嵌入 + bge-reranker 重排（SiliconFlow）+ 重跑真实评测
- [ ] W6 生产化验收：Docker 全栈（Postgres + Milvus standalone + Celery）+ 数据重灌 + 演示
