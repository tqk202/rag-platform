# rag-platform · 企业知识库 RAG 问答平台

[![CI](https://github.com/tqk202/rag-platform/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/tqk202/rag-platform/actions)

> 面向真实企业场景的检索增强生成（RAG）问答系统，突出工程化落地：多租户权限隔离、文档生命周期管理、异步文档处理、全链路可观测与质量评测体系。

## 功能特性

- **混合检索 + 重排**：向量召回（bge-m3）+ BM25 稀疏索引双路召回，RRF 融合，bge-reranker 精排
- **多租户权限**：RBAC 角色门卫 + 部门级数据隔离（检索层元数据过滤）
- **文档生命周期**：解析 → 切片 → 嵌入 → 入库异步管线；重传升版、删除双存储同步清理
- **可信回答**：引文溯源 + 无答案识别（拒绝回答），每条回答可追溯
- **回答缓存**：语义缓存热问题秒回，降低 LLM 调用成本
- **可观测与防护**：request_id 全链路追踪、令牌桶限流、外部依赖容错重试
- **质量评测**：黄金评测集 + RAGAS 风格指标 + CI 质量护栏

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · SQLAlchemy 2 (async) · Celery |
| 前端 | Vue 3 · TypeScript · Element Plus · Vite |
| 向量库 | Milvus（元数据过滤实现权限隔离） |
| 元数据库 | PostgreSQL 16 |
| 模型 | LLM：DeepSeek / Qwen（OpenAI 兼容）· Embedding / Rerank：bge-m3 / bge-reranker |
| 部署 | Docker Compose |

## 快速开始

### 开发模式（无需 Docker，Windows 友好）

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
# backend/.env 已配置轻量模式：SQLite + Milvus Lite（本地文件）
.venv\Scripts\python -m alembic upgrade head   # 应用数据库迁移（首次建表）
uvicorn app.main:app --reload
```

### 生产部署（Docker Compose）

```bash
# 1. 环境变量（backend/.env 放真实 API key，gitignored 不进镜像）
cp .env.example .env

# 2. 构建并启动全部服务（Postgres / Redis / Milvus / 后端 / Worker / 前端）
#    后端容器启动时会自动执行 `alembic upgrade head`（数据库迁移）再起服务
docker compose up -d --build

# 3. 灌入演示数据（演示账号 admin / mgr_hr / member_hr，密码均 123456；
#    seed 重建库后会自动 stamp 到当前迁移版本）
docker compose exec backend python scripts/seed_dev.py

# 4. 访问
#   前端: http://localhost:5173
#   后端 API 文档: http://localhost:8000/docs
```

开发 / 生产通过环境变量切换：`DATABASE_URL`（SQLite / PostgreSQL）、`VECTOR_URI`（Milvus 本地文件 / 服务地址）、`INGESTION_MODE`（inline / async）。

## 评测

黄金评测集（52 可答题 + 3 拒答题）+ RAGAS 风格四指标 + 拒答准确率。CI 每次提交自动跑离线评测，质量回退即失败：

```bash
cd backend
.venv\Scripts\python scripts/ablation.py api real   # 全真实评测（bge-m3 嵌入 + bge-reranker 重排 + DeepSeek 裁判）
.venv\Scripts\python scripts/ablation.py            # mock 模式（离线、免费，验证流程）
```

## 数据库迁移（Alembic）

schema 版本化迁移：**改表结构不再需要清库重灌**，老库原地升级、数据不丢。
后端容器启动前自动执行 `alembic upgrade head`；本地开发需手动跑一次。

```bash
cd backend
.venv\Scripts\python -m alembic upgrade head     # 应用全部迁移到最新
.venv\Scripts\python -m alembic revision --autogenerate -m "add xxx"   # 改完模型后生成新迁移
.venv\Scripts\python -m alembic downgrade base   # 回退到空库（本地演示用）
.venv\Scripts\python -m alembic check            # 校验「模型 ↔ 迁移」是否同步（CI 也会跑）
```

说明：
- 项目是纯 async 数据库驱动，采用 Alembic 的 async 迁移模板（`alembic init -t async`）。
- 稀疏索引表 `chunks_fts`（FTS5 / PG GIN 双实现）不在 ORM 元数据里，由迁移手写 SQL 按方言建表，`include_object` 过滤器把它排除出 autogenerate 对比。
- `seed_dev.py` / `run_eval.py` 整库重建后会自动 `alembic stamp head`，保证版本表与 schema 一致。

## 项目结构

```
backend/            # FastAPI 后端
│  alembic/         # 数据库迁移（Alembic async 模板 + 版本迁移）
│  alembic.ini      # Alembic 配置
│  app/api/         # 路由层（认证 / 文档 / 问答 / 管理）
│  app/services/    # 业务逻辑（文档 / 检索 / 问答 / 向量 / 评测）
│  app/models/      # 数据库模型
│  app/schemas/     # API 请求 / 响应
│  app/core/        # 配置、安全、异常、限流
│  app/tasks/       # Celery 异步任务
│  scripts/         # seed 灌库、评测脚本
│  tests/           # 113 个自动化测试
frontend/           # Vue 3 前端
docs/
   architecture.md  # 架构说明
```

## 质量与 CI

- 113 个自动化测试（pytest）+ ruff 静态检查
- GitHub Actions：push / PR 自动跑测试、lint、黄金评测护栏、Alembic 迁移校验（迁移可跑 + 模型与迁移同步）

## 文档

- [架构说明](docs/architecture.md)
- GitHub 仓库：[tqk202/rag-platform](https://github.com/tqk202/rag-platform)
