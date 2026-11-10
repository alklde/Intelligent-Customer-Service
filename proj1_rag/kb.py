"""知识库文档与向量索引的唯一读写入口。

设计要点：
- Redis 是文档事实源（`kb:doc:{id}`），Qdrant 只是可重建的向量索引；
- 文档入库前统一清洗、校验、SHA-256 去重并分块，避免脏数据；
- 向量 point id 由文档 ID 与块序号确定性生成，重复灌库不会产生脏点；
- 删除文档时同步清理全部向量；索引丢失时可由 Redis 文档重建。

所有方法为同步实现：供 proj1 API（线程池）、智能客服图节点与
本地种子脚本复用，避免维护两套异步逻辑。
"""

import hashlib
import math
import re
import time
import uuid
from collections import Counter

import redis as sync_redis
from langchain_core.documents import Document
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import settings
from core.llm_factory import get_embeddings

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2028\u2029\ufeff]")
_MULTI_BLANK = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")

NO_INFO_ANSWER = "抱歉，知识库暂无相关信息。您可以换个问法，或说「转人工」由客服协助处理。"


class KBError(Exception):
    """知识库业务异常：由路由层转换为对应 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_text(text: str) -> str:
    """清洗正文：去零宽字符、统一换行、压缩空白与连续空行。"""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _ZERO_WIDTH.sub("", cleaned)
    lines = [_SPACES.sub(" ", line).strip() for line in cleaned.split("\n")]
    cleaned = "\n".join(lines)
    return _MULTI_BLANK.sub("\n\n", cleaned).strip()


def content_hash(text: str) -> str:
    """规范化正文的 SHA-256，用于去重。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str) -> list[str]:
    """按段落聚合分块，块间保留重叠窗口，保证语义连续且块长可控。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > settings.kb_chunk_size:
            sentences = re.split(r"(?<=[。！？!?；;])", paragraph)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(sentence) > settings.kb_chunk_size:
                    for start in range(0, len(sentence), settings.kb_chunk_size):
                        piece = sentence[start : start + settings.kb_chunk_size]
                        if buffer:
                            chunks.append(buffer)
                            buffer = ""
                        chunks.append(piece)
                    continue
                if len(buffer) + len(sentence) <= settings.kb_chunk_size:
                    buffer += sentence
                else:
                    if buffer:
                        chunks.append(buffer)
                    buffer = sentence
            continue
        if len(buffer) + len(paragraph) <= settings.kb_chunk_size:
            buffer += ("\n" if buffer else "") + paragraph
        else:
            if buffer:
                chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)

    # 块间重叠：把上一块尾部的重叠文本拼到下一块开头
    if settings.kb_chunk_overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for index in range(1, len(chunks)):
            tail = chunks[index - 1][-settings.kb_chunk_overlap :]
            overlapped.append((tail + "\n" + chunks[index]).strip())
        chunks = overlapped
    return [chunk for chunk in chunks if chunk.strip()]


def _bigrams(text: str) -> set[str]:
    """提取字符二元组，用于 IDF 关键词通道。"""
    clean = re.sub(r"\s+", "", text or "")
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


class KBStore:
    """文档存储 + 向量索引的统一封装。"""

    def __init__(self):
        self.redis = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.client = QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout)
        self.collection = settings.qdrant_collection

    # ==================== 集合管理 ====================

    def ensure_collection(self) -> None:
        """集合不存在时按全局维度创建。"""
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            )
            logger.info("已创建 Qdrant 集合: {} (dim={})", self.collection, settings.embedding_dim)

    def point_count(self) -> int:
        """当前索引中的向量数量；集合不存在返回 0。"""
        if not self.client.collection_exists(self.collection):
            return 0
        return int(self.client.count(self.collection).count)

    # ==================== 文档 CRUD ====================

    def _validate(self, title: str, content: str) -> tuple[str, str]:
        """校验并规范化标题与正文。"""
        clean_title = normalize_text(title).replace("\n", " ")
        if not clean_title or len(clean_title) > 80:
            raise KBError("标题需为 1-80 个字符", status_code=400)
        clean_content = normalize_text(content)
        if len(clean_content) < settings.kb_min_chars:
            raise KBError(f"正文至少 {settings.kb_min_chars} 个字符", status_code=400)
        if len(clean_content) > settings.kb_max_chars:
            raise KBError(f"正文不能超过 {settings.kb_max_chars} 个字符", status_code=400)
        return clean_title, clean_content

    def _public(self, data: dict, with_content: bool = False) -> dict:
        """文档响应脱敏/裁剪：列表不返回全文。"""
        payload = {
            "doc_id": data.get("doc_id", ""),
            "title": data.get("title", ""),
            "source": data.get("source", "manual"),
            "chunk_count": int(data.get("chunk_count", 0)),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "created_by": data.get("created_by", ""),
        }
        if with_content:
            payload["content"] = data.get("content", "")
        return payload

    def add_document(
        self, title: str, content: str, source: str = "manual", created_by: str = "admin"
    ) -> dict:
        """新增文档：清洗 → 校验 → 去重 → 分块 → 向量化 → 双写。"""
        clean_title, clean_content = self._validate(title, content)
        digest = content_hash(clean_content)
        existing = self.redis.get(f"kb:doc_hash:{digest}")
        if existing:
            raise KBError(f"内容重复，已存在文档: {existing}", status_code=409)

        chunks = chunk_text(clean_content)
        if not chunks:
            raise KBError("正文无法切分为有效内容", status_code=400)

        # 先完成向量化，失败则整体失败，不产生半成品文档
        try:
            vectors = get_embeddings().embed_documents(
                [f"search_document: {chunk}" for chunk in chunks]
            )
        except Exception as exc:
            logger.error("文档向量化失败: {}", exc)
            raise KBError("向量化服务不可用，请稍后重试", status_code=503)

        self.ensure_collection()
        doc_id = f"kb_{uuid.uuid4().hex[:12]}"
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{index}")),
                vector=vector,
                payload={
                    "content": chunk,
                    "metadata": {
                        "doc_id": doc_id,
                        "title": clean_title,
                        "source": source,
                        "chunk_index": index,
                    },
                },
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        self.client.upsert(collection_name=self.collection, points=points)

        now = time.time()
        mapping = {
            "doc_id": doc_id,
            "title": clean_title,
            "content": clean_content,
            "content_hash": digest,
            "source": source,
            "chunk_count": len(chunks),
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
        }
        pipe = self.redis.pipeline(transaction=True)
        pipe.hset(f"kb:doc:{doc_id}", mapping=mapping)
        pipe.set(f"kb:doc_hash:{digest}", doc_id)
        pipe.zadd("index:kb_docs", {doc_id: now})
        pipe.execute()
        logger.info("知识库文档已入库: {} ({} 块) title={}", doc_id, len(chunks), clean_title)
        return self._public(mapping)

    def list_documents(self) -> list[dict]:
        """文档列表（按创建时间倒序，不含全文）。"""
        doc_ids = self.redis.zrevrange("index:kb_docs", 0, -1)
        documents = []
        for doc_id in doc_ids:
            data = self.redis.hgetall(f"kb:doc:{doc_id}")
            if not data:
                self.redis.zrem("index:kb_docs", doc_id)
                continue
            documents.append(self._public(data))
        return documents

    def get_document(self, doc_id: str) -> dict | None:
        """文档详情（含全文）。"""
        data = self.redis.hgetall(f"kb:doc:{doc_id}")
        return self._public(data, with_content=True) if data else None

    def delete_document(self, doc_id: str) -> bool:
        """删除文档：先删向量，再删 Redis 与索引。"""
        data = self.redis.hgetall(f"kb:doc:{doc_id}")
        if not data:
            return False
        if self.client.collection_exists(self.collection):
            self.client.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=[FieldCondition(key="metadata.doc_id", match=MatchValue(value=doc_id))]
                ),
            )
        pipe = self.redis.pipeline(transaction=True)
        pipe.delete(f"kb:doc:{doc_id}", f"kb:doc_hash:{data.get('content_hash', '')}")
        pipe.zrem("index:kb_docs", doc_id)
        pipe.execute()
        logger.info("知识库文档已删除: {}", doc_id)
        return True

    # ==================== 索引重建 ====================

    def reindex(self) -> dict:
        """按 Redis 事实源全量重建 Qdrant 索引。"""
        doc_ids = self.redis.zrange("index:kb_docs", 0, -1)
        if not doc_ids:
            raise KBError("知识库为空，无可重建文档", status_code=400)

        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.ensure_collection()

        total_chunks = 0
        for doc_id in doc_ids:
            data = self.redis.hgetall(f"kb:doc:{doc_id}")
            if not data:
                continue
            chunks = chunk_text(data.get("content", ""))
            if not chunks:
                continue
            try:
                vectors = get_embeddings().embed_documents(
                    [f"search_document: {chunk}" for chunk in chunks]
                )
            except Exception as exc:
                logger.error("重建时向量化失败 doc={}: {}", doc_id, exc)
                raise KBError("向量化服务不可用，重建中断", status_code=503)
            points = [
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{index}")),
                    vector=vector,
                    payload={
                        "content": chunk,
                        "metadata": {
                            "doc_id": doc_id,
                            "title": data.get("title", ""),
                            "source": data.get("source", ""),
                            "chunk_index": index,
                        },
                    },
                )
                for index, (chunk, vector) in enumerate(zip(chunks, vectors))
            ]
            self.client.upsert(collection_name=self.collection, points=points)
            self.redis.hset(f"kb:doc:{doc_id}", "chunk_count", len(chunks))
            total_chunks += len(chunks)
        logger.info("知识库索引重建完成: {} 篇文档 / {} 个分块", len(doc_ids), total_chunks)
        return {"documents": len(doc_ids), "chunks": total_chunks}

    def sync_on_startup(self) -> None:
        """启动自检：索引为空但 Redis 有文档时自动重建，保证重启不丢检索能力。"""
        try:
            doc_count = int(self.redis.zcard("index:kb_docs"))
            if doc_count == 0:
                logger.info("知识库尚无文档，等待管理员录入或执行 seed_rag.py")
                return
            self.ensure_collection()
            if self.point_count() == 0:
                logger.warning("向量索引为空，正在从 Redis 文档自动重建（{} 篇）", doc_count)
                self.reindex()
            else:
                logger.info("知识库自检通过: {} 篇文档 / {} 个向量", doc_count, self.point_count())
        except Exception as exc:
            logger.error("知识库启动自检失败（不影响服务启动）: {}", exc)

    # ==================== 检索 ====================

    def retrieve(self, query: str, limit: int | None = None) -> list[Document]:
        """混合检索：向量相似度 + IDF 关键词覆盖率，返回分块文档。"""
        self.ensure_collection()
        top_k = limit or max(settings.qdrant_top_k + 4, 8)
        query_vector = get_embeddings().embed_query(f"search_query: {query}")
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=max(top_k * 3, 16),
            with_payload=True,
        )
        records, _ = self.client.scroll(collection_name=self.collection, limit=1000, with_payload=True)

        corpus: list[tuple[dict, set[str]]] = []
        for record in records:
            payload = record.payload or {}
            content = payload.get("content", "")
            if content:
                corpus.append((payload, _bigrams(content)))

        query_grams = _bigrams(query)
        df: Counter = Counter()
        for _payload, grams in corpus:
            df.update(grams)
        idf = {
            gram: math.log((len(corpus) + 1) / (df.get(gram, 0) + 1)) + 1.0
            for gram in query_grams
        }
        idf_total = sum(idf.values()) or 1.0

        scored: dict[str, float] = {}
        payloads: dict[str, dict] = {}
        for point in response.points:
            payload = point.payload or {}
            content = payload.get("content", "")
            if not content:
                continue
            scored[content] = max(scored.get(content, 0.0), 0.45 * float(point.score))
            payloads[content] = payload

        for payload, grams in corpus:
            content = payload.get("content", "")
            matched = sum(weight for gram, weight in idf.items() if gram in grams)
            keyword_score = 0.55 * (matched / idf_total)
            if keyword_score <= 0:
                continue
            scored[content] = scored.get(content, 0.0) + keyword_score
            payloads.setdefault(content, payload)

        ranked = sorted(scored.items(), key=lambda item: item[1], reverse=True)
        documents = []
        for content, score in ranked[:top_k]:
            metadata = dict(payloads.get(content, {}).get("metadata", {}))
            metadata["retrieval_score"] = round(score, 4)
            documents.append(Document(page_content=content, metadata=metadata))
        logger.info("知识库检索完成: query='{}' 返回 {} 个分块", query, len(documents))
        return documents


kb_store = KBStore()