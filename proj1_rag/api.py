"""Agentic RAG 与知识库服务的 FastAPI 路由。

- 知识库管理（仅管理员）：文档列表 / 新增 / 删除 / 重建索引
- 知识库检索（仅客服）：必须绑定本人正在处理的会话（human_handling）
- /query：管理员调试入口（保留原 RAG 图能力）
知识库不再对客户暴露，也不再提供绕过校验的原始灌库接口。
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from core.auth_deps import AuthContext, require_admin, require_staff
from proj1_rag.graph import rag_graph
from proj1_rag.kb import KBError, NO_INFO_ANSWER, kb_store
from proj2_customer_service.store import SessionStatus, SessionStore

store = SessionStore()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动自检：索引丢失时从 Redis 文档自动重建，保证重启后知识库可用。"""
    await asyncio.to_thread(kb_store.sync_on_startup)
    yield


app = FastAPI(title="Agentic RAG 知识库", version="3.0.0", lifespan=lifespan)


# ==================== 请求 / 响应模型 ====================


class DocumentCreateRequest(BaseModel):
    """管理员新增知识库文档。"""

    title: str = Field(..., min_length=1, max_length=80, description="文档标题")
    content: str = Field(..., min_length=1, description="文档正文（Markdown / 纯文本）")
    source: str = Field(default="manual", max_length=32, description="来源标记：manual / upload / seed")


class QueryRequest(BaseModel):
    """管理员调试查询。"""

    query: str = Field(..., min_length=1, description="用户查询")


class QueryResponse(BaseModel):
    """RAG 查询响应，附带过程指标便于观测。"""

    query: str
    answer: str
    used_web_search: bool = Field(..., description="本次回答是否走了 Mock 网络搜索兜底")
    hallucination_score: float = Field(..., description="最终答案的幻觉分数")


class KBSearchRequest(BaseModel):
    """客服在会话中检索知识库。"""

    query: str = Field(..., min_length=1, max_length=200, description="检索问题")
    session_id: str = Field(..., min_length=1, description="正在处理的会话 ID")


def _raise(exc: KBError) -> None:
    """把知识库业务异常转换为 HTTP 异常。"""
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


# ==================== 基础端点 ====================


@app.get("/")
def root() -> dict:
    """服务欢迎页。"""
    return {
        "service": "Agentic RAG 知识库",
        "docs": "/docs",
        "endpoints": {
            "GET /kb/documents": "知识库文档列表（管理员）",
            "POST /kb/documents": "新增文档（管理员）",
            "DELETE /kb/documents/{id}": "删除文档（管理员）",
            "POST /kb/reindex": "重建索引（管理员）",
            "POST /kb/search": "会话内检索（客服，需 human_handling 会话）",
            "POST /query": "管理员调试查询",
            "GET /health": "健康探针",
        },
    }


@app.get("/health")
def health() -> dict:
    """健康探针（含索引与文档计数）。"""
    try:
        documents = int(kb_store.redis.zcard("index:kb_docs"))
        points = kb_store.point_count()
        return {"status": "ok", "service": "proj1_rag", "documents": documents, "vectors": points}
    except Exception as exc:
        logger.error("健康探针检查失败: {}", exc)
        return {"status": "ok", "service": "proj1_rag", "documents": -1, "vectors": -1}


# ==================== 知识库管理（管理员） ====================


@app.get("/kb/documents")
def list_documents(_auth: AuthContext = Depends(require_admin)) -> list[dict]:
    """文档列表（不含全文）。"""
    return kb_store.list_documents()


@app.get("/kb/documents/{doc_id}")
def get_document(doc_id: str, _auth: AuthContext = Depends(require_admin)) -> dict:
    """文档详情（含全文）。"""
    document = kb_store.get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return document


@app.post("/kb/documents")
def create_document(req: DocumentCreateRequest, auth: AuthContext = Depends(require_admin)) -> dict:
    """新增文档：清洗、校验、去重、分块、向量化后入库。"""
    try:
        return kb_store.add_document(req.title, req.content, req.source, created_by=auth.subject)
    except KBError as exc:
        _raise(exc)
    except Exception as exc:
        logger.error("新增文档失败: {}", exc)
        raise HTTPException(status_code=500, detail="文档入库失败")


@app.delete("/kb/documents/{doc_id}")
def delete_document(doc_id: str, _auth: AuthContext = Depends(require_admin)) -> dict:
    """删除文档并同步清理向量索引。"""
    if not kb_store.delete_document(doc_id):
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return {"ok": True, "detail": "文档已删除"}


@app.post("/kb/reindex")
def reindex(_auth: AuthContext = Depends(require_admin)) -> dict:
    """按 Redis 文档事实源全量重建向量索引。"""
    try:
        result = kb_store.reindex()
        return {"ok": True, **result}
    except KBError as exc:
        _raise(exc)
    except Exception as exc:
        logger.error("索引重建失败: {}", exc)
        raise HTTPException(status_code=500, detail="索引重建失败")


# ==================== 会话内检索（客服） ====================


def _search_sync(query: str) -> dict:
    """执行 RAG 图并整理可展示的知识库依据。"""
    result = rag_graph.invoke({"query": query}, config={"recursion_limit": 25})
    documents = result.get("documents", [])
    used_web = any(doc.metadata.get("source") == "web_search_mock" for doc in documents)
    sources = [
        {
            "doc_id": doc.metadata.get("doc_id", ""),
            "title": doc.metadata.get("title", ""),
            "content": doc.page_content,
            "score": doc.metadata.get("retrieval_score", 0),
        }
        for doc in documents
        if doc.metadata.get("source") != "web_search_mock"
    ]
    answer = result.get("generation", "").strip()
    found = bool(sources) and not used_web and answer and NO_INFO_ANSWER not in answer
    return {
        "answer": answer if found else NO_INFO_ANSWER,
        "sources": sources,
        "found": found,
        "hallucination_score": result.get("hallucination_score", 0.0),
    }


@app.post("/kb/search")
async def kb_search(req: KBSearchRequest, auth: AuthContext = Depends(require_staff)) -> dict:
    """客服检索：校验会话归属与状态后，返回知识库接地答案与依据。"""
    session = await store.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {req.session_id}")
    if session.get("agent_id") != auth.subject:
        raise HTTPException(status_code=403, detail="只能检索自己接入的会话")
    if session.get("status") != SessionStatus.HUMAN_HANDLING.value:
        raise HTTPException(status_code=409, detail="仅人工处理中的会话可检索知识库")
    try:
        return await asyncio.to_thread(_search_sync, req.query)
    except Exception as exc:
        logger.error("知识库检索失败: {}", exc)
        raise HTTPException(status_code=500, detail="知识库检索失败")


# ==================== 管理员调试查询 ====================


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, _auth: AuthContext = Depends(require_admin)) -> QueryResponse:
    """执行 Agentic RAG 图并返回最终答案（仅管理员调试）。"""
    try:
        result = rag_graph.invoke({"query": req.query}, config={"recursion_limit": 25})
        used_web_search = any(
            doc.metadata.get("source") == "web_search_mock"
            for doc in result.get("documents", [])
        )
        return QueryResponse(
            query=req.query,
            answer=result.get("generation", ""),
            used_web_search=used_web_search,
            hallucination_score=result.get("hallucination_score", 0.0),
        )
    except Exception as exc:
        logger.error("RAG 图执行失败: {}", exc)
        raise HTTPException(status_code=500, detail="RAG 服务内部错误")