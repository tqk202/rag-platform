"""全局配置：从环境变量 / .env 读取，pydantic 负责类型校验。"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 部门清单（注册下拉用，单一来源）。value 必须与文档的 department 字段一致，
# 知识库隔离按此对齐；演示库只有 hr 有文档，其他部门注册后知识库为空正好演示隔离。
DEPARTMENTS: list[dict[str, str]] = [
    {"value": "hr", "label": "人力资源部"},
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    APP_NAME: str = "rag-platform"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # 安全
    SECRET_KEY: str = "change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # 基础设施
    DATABASE_URL: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    REDIS_URL: str = "redis://localhost:6379/0"
    # 命名刻意避开 "MILVUS_URI"：pymilvus 会读取同名环境变量，冲突会污染 import
    VECTOR_URI: str = "http://localhost:19530"  # 本地文件(开发) 或 http://milvus:19530(生产)

    # 模型服务（OpenAI 兼容协议，可无缝切换 DeepSeek/Qwen/OpenAI）
    LLM_BACKEND: str = "mock"  # mock(当前) | api —— 先跑通链路，再填 key 切换
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"  # SiliconFlow 模型名（OpenAI 兼容 /embeddings）

    # 重排模型服务（OpenAI 兼容，SiliconFlow 等）：真实 cross-encoder
    RERANKER_BASE_URL: str = ""
    RERANKER_API_KEY: str = ""
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # 文档处理（W1）
    CHUNK_SIZE: int = 500            # 每块字符数，W4 消融实验会调它
    CHUNK_OVERLAP: int = 50          # 块间重叠，避免语义被切断
    EMBEDDING_BACKEND: str = "mock"  # mock(当前) | api | local
    EMBEDDING_DIM: int = 1024        # bge-m3 输出维度
    INGESTION_MODE: str = "async"    # async(Celery生产) | inline(开发直接处理)
    MILVUS_COLLECTION: str = "rag_chunks"

    # 上传安全边界（W6）：类型白名单 + 大小上限，防误传/恶意文件撑爆内存
    ALLOWED_UPLOAD_EXTENSIONS: str = ".txt,.md,.pdf,.doc,.docx"
    MAX_UPLOAD_SIZE_MB: int = 20

    # 重排（W2.5c）：召回 -> 重排精排 -> 取前 N 给 LLM
    RERANKER_BACKEND: str = "lexical"  # lexical(词法,离线) | api(真实 bge-reranker,生产) | none(关闭,W4 消融)
    RERANK_RECALL_K: int = 20          # 召回宽度：先召回 N 条再交给重排
    RERANK_TOP_N: int = 5              # 重排后取前 N 条给 LLM
    CITATION_MIN_SCORE_RATIO: float = 0.5  # 引文过滤：重排分低于最强引文该比例者剔除（只留强相关）

    # 上下文预算（P1-6）：LLM 每次调用都花钱，检索结果按 token 预算动态截断，
    # 防长文档上下文溢出 + 成本失控；输出也设上限
    MAX_CONTEXT_TOKENS: int = 4000   # 输入上下文预算（含问题 + 检索切片 + 提示词）
    MAX_OUTPUT_TOKENS: int = 1024    # 输出上限（max_tokens）

    # 限流（W5）：LLM 接口每次调用都花钱，防止单用户刷爆 / 被爬虫打
    RATE_LIMIT_RPM: int = 30           # 每用户每分钟允许的 /chat 请求数（token bucket 稳态速率）

    # 回答缓存（W11）：热问题秒回 + 省 LLM 调用。语义命中：Milvus 存问句向量，
    # KV（Redis/内存）存回答负载；部门版本号失效 + TTL 双保险
    ANSWER_CACHE_ENABLED: bool = True
    ANSWER_CACHE_BACKEND: str = "redis"  # redis(生产) | memory(测试/无 Redis 环境)
    ANSWER_CACHE_TTL_SECONDS: int = 86400            # 缓存 24h，防止无限膨胀
    ANSWER_CACHE_SIMILARITY_THRESHOLD: float = 0.95  # 问句余弦相似度阈值，>= 算命中
    ANSWER_CACHE_MILVUS_COLLECTION: str = "question_cache"

    @model_validator(mode="after")
    def _secret_not_weak_in_production(self):
        """P1-3 生产防线：默认占位密钥直接拒绝启动，防带病上线。"""
        if self.ENVIRONMENT == "production" and (
            not self.SECRET_KEY or self.SECRET_KEY == "change-me"
        ):
            raise ValueError("生产环境必须设置强 SECRET_KEY（backend/.env 配置），拒绝启动")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
