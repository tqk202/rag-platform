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
    # P1-4 CORS 白名单：逗号分隔；生产设为前端域名（如 http://localhost:5173）
    CORS_ORIGINS: str = "*"

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

    # 文档处理（W1）：CHUNK_SIZE/CHUNK_OVERLAP 是通用默认（回退值），
    # 各格式有自己的最优大小——Markdown 标题感知（技术文档大），PDF/DOCX 正式文档偏小
    CHUNK_SIZE: int = 500            # 通用默认每块字符数（回退值）
    CHUNK_OVERLAP: int = 50          # 通用默认块间重叠（回退值，类型化时按 1/5 自动算）
    CHUNK_SIZE_MD: int = 800         # Markdown：标题感知切分（技术文档 600-1000）
    CHUNK_SIZE_PDF: int = 600        # PDF：以页为界优先（正式文档）
    CHUNK_SIZE_DOCX: int = 600       # DOCX：段落感知（合同/正式文档 400-600）
    CHUNK_SIZE_TXT: int = 500        # 纯文本：通用句子对齐（保留原默认）
    TEXT_CLEANING: str = "none"      # none(原样入库) | basic(保守清洗:页眉残留/全角空格/行尾空白)
    OCR_BACKEND: str = "none"        # none(不启用) | rapidocr(扫描版 PDF OCR)
    OCR_MIN_TEXT_CHARS: int = 5      # 扫描页判定：单页有效文本低于该字符数（空页/纯页码页）才走 OCR
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

    # 查询改写：off(默认,不改写,评测基线稳定) | rule(纯规则,零成本) | llm(LLM 改写,mock 兜底回退规则)
    QUERY_REWRITE: str = "off"

    # 上下文预算（P1-6）：LLM 每次调用都花钱，检索结果按 token 预算动态截断，
    # 防长文档上下文溢出 + 成本失控；输出也设上限
    MAX_CONTEXT_TOKENS: int = 4000   # 输入上下文预算（含问题 + 检索切片 + 提示词）
    MAX_OUTPUT_TOKENS: int = 1024    # 输出上限（max_tokens）

    # 多轮对话（P2-1）：把最近几轮历史喂给 LLM，追问才有上下文
    MAX_HISTORY_TURNS: int = 6       # 最近 N 轮（每轮 user+assistant 两条）
    MAX_HISTORY_CHARS: int = 800     # 每条历史内容截断，防上下文污染

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
