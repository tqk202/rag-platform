# rag-platform · 企业知识库 RAG 问答平台

> 一个面向真实企业场景的检索增强生成（RAG）问答系统。用于求职作品集，突出**工程化落地能力**：多租户权限、文档生命周期、异步文档处理、全链路可观测、评测体系。

## 为什么不是 demo

面试官看 RAG 项目只关心七个问题，本项目的设计逐条对应：

| 面试官会问 | 本项目怎么答 |
|---|---|
| 回答质量怎么度量？ | 评测体系：黄金评测集 + RAGAS 指标 + 消融实验 |
| 多部门数据权限怎么隔离？ | 多租户 + 文档级/片段级权限（元数据过滤） |
| 文档更新/删除会过时吗？ | 文档版本管理与增量同步 |
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
- [x] W2.5c Rerank 重排：召回(20)→重排→取前5→生成三层管线（RerankerProvider 接口抽象 + 轻量词法实现，可升级 bge-reranker）
- [ ] W3 多租户权限：RBAC + 元数据过滤 + 越权测试
- [ ] W4 评测体系：黄金评测集 + RAGAS + 消融实验
- [ ] W5 工程规范：测试 / CI / 可观测 / 限流
- [ ] W6 边界打磨与作品化：README 作品化
