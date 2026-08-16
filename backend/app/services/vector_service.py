"""向量库封装：建集 / 写入 / 检索 / 删除。

URI 指向本地文件 -> Milvus Lite（开发，零 Docker）；
URI 指向 http://  -> Milvus standalone（Docker/生产）。
"""
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

COLLECTION_NAME = settings.MILVUS_COLLECTION
DIM = settings.EMBEDDING_DIM


def quote_filter(value: str) -> str:
    """Milvus 表达式字符串字面量：双引号内直接写非 ASCII 解析失败（invalid parameter），
    统一用单引号包裹并对内部引号/反斜杠转义。"""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class VectorStore:
    def __init__(self, uri: str):
        self.uri = uri
        self._client: Any | None = None
        self._ensure_local_dir()

    def _ensure_local_dir(self) -> None:
        """Milvus Lite 本地文件模式要求父目录已存在。"""
        if not (self.uri.startswith("http://") or self.uri.startswith("https://")):
            Path(self.uri).parent.mkdir(parents=True, exist_ok=True)

    @property
    def client(self) -> Any:
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(uri=self.uri)
        return self._client

    def _collection_missing_kb_field(self) -> bool:
        """已存在的集合是否缺 knowledge_base 字段（多知识库 schema 升级判断）。"""
        desc = self.client.describe_collection(COLLECTION_NAME)
        fields = desc.get("fields", [])
        return all(f.get("name") != "knowledge_base" for f in fields)

    def ensure_collection(self, dim: int = DIM) -> None:
        if self.client.has_collection(COLLECTION_NAME):
            # 多知识库 schema 升级：集合存在但缺 knowledge_base 字段 -> 自愈重建
            # （Milvus 不支持原地加字段；旧库重建后由重灌/对账回填数据）
            if self._collection_missing_kb_field():
                logger.warning(
                    "向量集合 %s 缺 knowledge_base 字段，重建（旧数据需重灌）",
                    COLLECTION_NAME,
                )
                self.client.drop_collection(COLLECTION_NAME)
            else:
                return

        from pymilvus import DataType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False)
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="document_id", datatype=DataType.INT64)
        schema.add_field(field_name="department", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="knowledge_base", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="page_no", datatype=DataType.INT32)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=8192)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")

        self.client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )

    def insert_chunks(self, rows: list[dict]) -> None:
        """rows: [{chunk_id, document_id, department, knowledge_base, page_no, content, vector}]"""
        self.ensure_collection()
        self.client.insert(collection_name=COLLECTION_NAME, data=rows)

    def search(
        self,
        query_vector: list[float],
        filter_expr: str | None = None,
        top_k: int = 5,
        output_fields: list[str] | None = None,
    ) -> list[Any]:
        self.ensure_collection()
        # Milvus 要求查询前先把集合加载进内存
        self.client.load_collection(COLLECTION_NAME)
        return self.client.search(
            collection_name=COLLECTION_NAME,
            data=[query_vector],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
        )[0]

    def delete_by_chunk_ids(self, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        self.ensure_collection()
        # 与 search 一致：先加载集合，Milvus 的删除/查询都要求在已加载集合上执行
        self.client.load_collection(COLLECTION_NAME)
        self.client.delete(collection_name=COLLECTION_NAME, ids=chunk_ids)

    def delete_by_document(self, document_id: int) -> None:
        """按文档删 Milvus 行（幂等，过滤式删除）。重灌/删除/对账都用它。"""
        if not self.client.has_collection(COLLECTION_NAME):
            return
        self.client.load_collection(COLLECTION_NAME)
        self.client.delete(
            collection_name=COLLECTION_NAME, filter=f"document_id == {document_id}"
        )

    def list_chunk_ids_by_document(self, document_id: int) -> list[int]:
        """列出该文档在 Milvus 里的所有 chunk_id（对账用）。"""
        self.ensure_collection()
        self.client.load_collection(COLLECTION_NAME)
        rows = self.client.query(
            collection_name=COLLECTION_NAME,
            filter=f"document_id == {document_id}",
            output_fields=["chunk_id"],
            limit=16384,  # Milvus query 单次上限，按文档切片规模足够
        )
        return [r["chunk_id"] for r in rows]


vector_store = VectorStore(uri=settings.VECTOR_URI)
