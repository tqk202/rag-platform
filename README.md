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

## 生产部署（Docker Compose 全栈）

一键拉起 6 类服务：Postgres 16（元数据）+ Redis（异步任务队列）+ etcd/MinIO/Milvus standalone（向量库）+ 后端 + Celery worker + 前端（nginx）：

```bash
# 1. 环境变量（两个文件，compose 按 [.env, backend/.env] 顺序注入，后者覆盖前者）
cp .env.example .env                  # 根 .env：通用配置（模型地址/安全/上传边界）
#   backend/.env：真实 API key（gitignored，经 backend/.dockerignore 不进镜像）
#   生产开关由 compose environment 强制：INGESTION_MODE=async、EMBEDDING_BACKEND=api 等

# 2. 构建并启动全部服务
docker compose up -d --build

# 3. 灌入演示数据（真实 bge-m3 嵌入；admin / mgr_hr / member_hr，密码均 123456）
docker compose exec backend python scripts/seed_dev.py

# 4. 访问
#   前端: http://localhost:5173（nginx 反代 /api → backend:8000）
#   后端 API: http://localhost:8000/docs
#   MinIO 控制台: http://localhost:9001 (minioadmin/minioadmin)
```

**这套编排里能讲的工程点**（对应面试考点，详见面试点.md W7）：

- **异步管线**：`INGESTION_MODE=async`，上传接口只投递 Celery 任务到 Redis 队列，worker 后台处理，前端轮询状态——接口秒回、大文档不卡（实测：828 字节文档 worker 2 秒处理完 pending→ready）。
- **SSE 流式反代**：nginx 必须 `proxy_buffering off` + `proxy_http_version 1.1` + 清空 `Connection` 头，否则回答会等整段结束才一次性到达（实测：经 nginx 43 个 delta 逐字推送）。
- **密钥不进镜像**：`backend/.dockerignore` 排除 `.env`/测试/本地库，真实 key 只经 compose `env_file` 在**运行时**注入——镜像可安全分发。
- **双容器共享上传目录**：backend 与 worker 共用 `uploads_data` 命名卷（`/app/data/uploads`），上传落盘的文件 worker 能读到同一份；容器以**非 root** 用户运行，去掉源码 bind-mount（生产正确形态，代价是改代码需重建镜像）。
- **健康检查依赖链**：etcd（`etcdctl`）+ MinIO（curl）健康 → Milvus（curl `/healthz`）健康 → backend 才启动。**实跑踩坑**：etcd 默认只监听 localhost，Milvus 在容器网络里连不上，必须 `command: etcd -listen-client-urls=http://0.0.0.0:2379 ...` 显式监听。
- **境内网络**：Docker Hub 直连超时，`~/.docker/daemon.json` 配置 `registry-mirrors`；构建阶段 Dockerfile 里也配了 pip 清华源 + npm 阿里镜像（否则 pip 直连 PyPI 卡 20 分钟+）。

**W7 实跑验收（全链路 E2E 通过）**：8 容器全健康 → 生产 seed 灌入 5 份企业级文档 / 43 切片（真实 bge-m3，1024 维向量入 PostgreSQL + Milvus）→ 注册/登录 → SSE 问答（真实 DeepSeek + 引文）→ 会话 → 改密（旧密码即失效）→ 越权防护（member 删文档 403 / admin 200）→ 删除联动清双存储。企业级加固后重跑：3 个表格/补偿类问题真实 LLM 全部带引文答对。

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
  空问题 / LLM 挂了 502 / SSE 错误事件 / 正常路径回归。企业级加固后**全量 105 测试通过 + 1 跳过**（真实 Redis 依赖的用例本地无 Redis 时跳过）。

## 文档版本管理（W6）

文档改了怎么办？同部门**重新上传同名文件**就是一次版本更新，不用删旧建新：

- 版本号自动 +1（列表接口和前端表格直接展示当前版本）。
- 旧切片**先清后灌**：Milvus 向量 + 数据库记录同步清掉再灌新内容，不会新旧数据混库。
- 相同内容重传直接拒绝（"已是最新版本"），不白处理一遍。
- 处理中的文档拒绝再次更新，避免异步模式下新旧处理任务抢数据。
- 3 个版本测试（`tests/test_versioning.py`）验证：升版、旧切片清理、同内容拒绝。

## 检索性能（W8）

关键词检索从「全表扫描 + 应用层 BM25（O(N)）」换成**数据库倒排索引（O(log N)）**：

- 开发/测试/评测：SQLite **FTS5** 虚拟表，`bm25()` 排名。
- 生产：PostgreSQL **tsvector + GIN 表达式索引**，`ts_rank()` 排序。
- 一个 `SparseIndex` 接口按数据库类型返回实现，延续"开发/生产配置分离、代码零改动"。
- 中文 jieba 分词空格拼接入索引，召回语义与旧 BM25 对齐（回归评测 4 指标不退化）。

## 容错重试（W9）

LLM / Embedding / Rerank 三个外部依赖统一接入**可恢复错误重试**，上游抖动不打断问答：

- 只重试瞬时故障：HTTP 429 / 5xx / 网络层错误（超时、连接重置）；4xx（400/401/422）**不重试**——重放必失败，白花钱。
- 指数退避 + 抖动：`base·2^n × (0.8~1.2)` 防重试风暴；429 优先遵循服务端 `Retry-After`（按上限封顶）。
- 重试耗尽抛错后自动落进既有 502 兜底（`UPSTREAM_ERROR` / `UPSTREAM_UNAVAILABLE`），与 W6 错误分层无缝衔接，零新增异常路径。
- **流式 SSE 刻意不重试**：内容已逐段吐给用户，重放会重复输出。
- 测试用 httpx.MockTransport 模拟上游故障（不花 API），7 个用例覆盖：500 重试成功 / 400 不重试 / 503 耗尽抛错 / 连接拒绝重试 / 嵌入与重排同样走重试 / Retry-After 封顶。

## 入库重试（W10）

W9 补的是「在线问答路径」的重试；W10 补「离线入库路径」——上传时嵌入接口抖动，任务不能静默失败卡住文档：

- **任务自动重试**：Celery 失败自动重试，复用 W9 的退避策略与状态码判断——只重试瞬时错误（嵌入 API 429/5xx、网络层故障），解析失败等永久错误直接失败（重放也必失败）。
- **失败原因落库**：`failure_reason` 写入文档记录，前端悬停即可看到失败原因，不再无声卡死。
- **手动重试接口**：`POST /documents/{id}/retry`，失败文档一键重新入队；仅 manager/admin、仅 failed 状态、部门隔离。

## 回答缓存（W11）

热点问题秒回 + 省 LLM 调用，问答走**语义缓存**（Redis 是这周第一次真正用上）：

- **语义命中**：问句向量化后在 Milvus `question_cache` 集合找相似问句（余弦相似度 ≥ 0.95），命中直接返回 Redis 里的完整回答（含引文），不再调 LLM——**换种问法也能命中**；mock 嵌入退化为精确匹配，不碍事。
- **权限隔离**：缓存键带 department——回答依赖该部门可见文档，键带部门就不会把 A 部门的回答串给 B 部门。
- **失效策略**：每部门一个「知识库版本号」（Redis 计数器），文档增/删/改/重试时 +1；缓存负载记录生成时的版本号，不一致即 miss。粗粒度但简单可靠，配 TTL（24h）双保险。
- **流式配合**：命中时整个回答一次推完（秒回），未命中照常流式、结束后回填缓存。
- **KV 可插拔**：redis（生产）/ memory（测试），沿用 W8 SparseIndex 的思路；全部读写 fail-open——缓存是优化不是依赖，Redis/Milvus 挂了问答照常走。

## 企业级加固（P1/P2 工程化）

面向「可交付企业级」的一次补强，专治 demo 到生产的四个命门——**数据一致性、安全、责任、质量护栏**：

- **跨存储一致性（P1-1）**：Milvus 不参与 DB 事务，崩溃会留孤儿向量。入库顺序固定为「DB 先提交 → Milvus 后写 → 置 ready」，失败清残留；新增**对账任务**（admin 端点 + Celery）以 DB 为准清孤儿向量、报告缺向量——外部存储偏差可收敛，不留"幽灵数据"。
- **安全纵深（P1-3）**：JWT 加 jti 登出**黑名单**（令牌立即失效）；登录按「用户名+IP」令牌桶限流防爆破（超限 429+Retry-After）；生产环境占位 `SECRET_KEY` 直接拒绝启动。
- **责任可追溯（P1-5）**：`audit_logs` 记录 谁/何时/对什么做了什么，与业务**同事务**提交；admin 按操作人/动作分页查询——能删数据不留痕的系统进不了企业。
- **成本与质量护栏（P1-6 / P2-6）**：检索切片按 token 预算动态截断（顺带修掉重排关闭时 20 条全进 LLM 的 bug）+ `max_tokens` 输出上限；CI 每次提交离线跑黄金集评测，与 committed 基线对比**质量回退即 CI 红**——质量不是上线时测一次，是每次提交都在守。
- **多轮对话（P2-1）**：最近几轮历史喂给 LLM，追问（"那上限呢？"）才有上下文；多轮请求不进回答缓存（含上下文，缓存会答非所问）。
- **生产部署（P1-4）**：后端多阶段 + **非 root** 镜像、全服务 `restart` + 资源限制、backend 健康检查、uploads 命名卷（去掉源码 bind-mount）、CORS 白名单配置化。
- **真实企业文档**：演示文档升级为带制度编号 / 多级标题 / 参数表格的企业级 Markdown（每份 8-9 切片，触发 Markdown 标题感知切分），黄金评测集跟随、基准不漂移。

**生产踩坑（都是只会在生产暴露的 bug）**：①PG 中文检索 `to_tsquery('simple', "'一线' OR '城市'")` 报 syntax error（SQLite 路径无恙）→ 改 `websearch_to_tsquery`；②seed 二次灌库撞 `chunks_fts` 主键（FTS 表不在 ORM 元数据里，drop_all 删不到）→ 补显式清稀疏索引。

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
- [x] W6 生产化验收：Docker 全栈（Postgres + Milvus standalone + Celery）+ 数据重灌 + 全链路 E2E
- [x] W8 检索性能：关键词检索从全表 + 内存 BM25 换成数据库倒排索引（FTS5 / PG tsvector 双实现）
- [x] W9 容错重试：LLM/Embedding/Rerank 统一重试策略（429/5xx/网络错误重试，指数退避+抖动，SSE 刻意不重试）
- [x] W10 入库重试：文档处理失败自动重试（瞬时/永久错误分类）+ 失败原因落库 + 手动重试接口
- [x] W11 回答缓存：语义缓存热问题秒回（Milvus 问句向量 + KV 负载）+ 部门版本号失效 + 权限隔离
- [x] P1 企业级加固：跨存储一致性对账 + 认证安全（登出黑名单/登录防爆破/弱密钥拦截）+ 审计日志 + 上下文预算 + 非 root 部署
- [x] P2 迭代优化：多轮对话进生成 + Markdown 标题感知切片 + CI 评测护栏
- [x] 演示文档企业化：制度编号/多级标题/参数表格的 .md + 黄金评测集跟随
