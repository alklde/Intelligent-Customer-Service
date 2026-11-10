"""RAG 初始知识库入库脚本（写入 Redis 文档库 + Qdrant 向量索引）。

数据来源：
1. 本地制度文档：proj1_rag/knowledge/*.md（离线兜底，始终参与入库）
2. 开源语料：ModelScope「QingshanAI/ecom-customer-service-synthetic」
   （Apache-2.0，992 条电商客服问答，自动下载并缓存到 knowledge/downloaded/）

特性：
- 复用 proj1_rag.kb.KBStore：统一清洗、校验、SHA-256 去重、分块与向量化；
- 幂等：重复执行时内容相同的文档自动跳过；
- `--reset`：清空旧索引与 Redis 文档后重建（用于结构升级 / 迁移）。

用法：
    python scripts/seed_rag.py                # 入库（默认采样 60 条问答）
    python scripts/seed_rag.py --reset        # 清空后重建
    python scripts/seed_rag.py --limit 120
    python scripts/seed_rag.py --no-download  # 仅本地制度文档
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proj1_rag.kb import KBError, kb_store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "proj1_rag" / "knowledge"
DOWNLOAD_DIR = KNOWLEDGE_DIR / "downloaded"
DATASET_URL = (
    "https://www.modelscope.cn/api/v1/datasets/QingshanAI/ecom-customer-service-synthetic"
    "/repo?Revision=master&FilePath=data.jsonl"
)


def download_dataset() -> list[dict]:
    """下载 ModelScope 开源客服语料（本地已有缓存则直接读取）。"""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cache = DOWNLOAD_DIR / "ecom_faq.jsonl"
    if not cache.exists():
        logger.info("下载开源客服语料: {}", DATASET_URL)
        with urllib.request.urlopen(DATASET_URL, timeout=60) as resp:
            cache.write_bytes(resp.read())
        logger.info("语料已缓存: {} ({} bytes)", cache, cache.stat().st_size)
    records = []
    with cache.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    logger.info("语料加载完成: {} 条", len(records))
    return records


def sample_by_scene(records: list[dict], limit: int) -> list[dict]:
    """按场景轮询采样，保证知识覆盖均衡。"""
    buckets: dict[str, list[dict]] = {}
    for record in records:
        scene = (record.get("scene") or "综合").strip() or "综合"
        buckets.setdefault(scene, []).append(record)
    picked: list[dict] = []
    index = 0
    while len(picked) < limit:
        added = False
        for bucket in buckets.values():
            if index < len(bucket) and len(picked) < limit:
                picked.append(bucket[index])
                added = True
        if not added:
            break
        index += 1
    return picked


def local_documents() -> list[tuple[str, str, str]]:
    """读取本地制度文档，返回 (标题, 正文, 来源)。"""
    documents = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        first_line = content.splitlines()[0].lstrip("# ").strip()
        documents.append((first_line or path.stem, content, "seed"))
    return documents


def downloaded_documents(records: list[dict]) -> list[tuple[str, str, str]]:
    """把问答记录转换为知识条目 (标题, 正文, 来源)。"""
    documents = []
    for record in records:
        scene = (record.get("scene") or "综合").strip()
        user = (record.get("user") or "").strip()
        bot = (record.get("bot") or "").strip()
        if user and bot:
            documents.append((f"客服问答 · {scene}", f"用户问题：{user}\n客服回复：{bot}", "seed"))
    return documents


def reset_kb() -> None:
    """清空向量索引与 Redis 文档（结构升级 / 迁移用）。"""
    if kb_store.client.collection_exists(kb_store.collection):
        kb_store.client.delete_collection(kb_store.collection)
    keys = kb_store.redis.keys("kb:doc:*") + kb_store.redis.keys("kb:doc_hash:*")
    if keys:
        kb_store.redis.delete(*keys)
    kb_store.redis.delete("index:kb_docs")
    logger.warning("已清空知识库文档与索引")


def main() -> None:
    """入口：组装文档 → 逐篇入库 → 汇总。"""
    parser = argparse.ArgumentParser(description="RAG 初始知识库入库")
    parser.add_argument("--limit", type=int, default=60, help="开源语料采样条数")
    parser.add_argument("--no-download", action="store_true", help="不下载开源语料")
    parser.add_argument("--reset", action="store_true", help="清空后重建")
    args = parser.parse_args()

    if args.reset:
        reset_kb()

    documents = local_documents()
    logger.info("本地制度文档: {} 篇", len(documents))

    if not args.no_download:
        try:
            records = download_dataset()
            sampled = sample_by_scene(records, args.limit)
            extra = downloaded_documents(sampled)
            documents.extend(extra)
            logger.info("开源语料采样: {} 条（场景覆盖 {} 个）", len(extra), len({r.get("scene") for r in sampled}))
        except Exception as exc:
            logger.warning("开源语料下载/解析失败，回退为仅本地文档: {}", exc)

    if not documents:
        raise SystemExit("没有可入库的文档")

    added = skipped = failed = 0
    for title, content, source in documents:
        try:
            kb_store.add_document(title, content, source=source, created_by="seed")
            added += 1
        except KBError as exc:
            if exc.status_code == 409:
                skipped += 1
                logger.info("文档已存在，跳过: {}", title)
            else:
                failed += 1
                logger.error("文档入库失败: {} -> {}", title, exc.message)
        except Exception as exc:
            failed += 1
            logger.error("文档入库异常: {} -> {}", title, exc)

    logger.info(
        "入库完成: 新增 {} / 跳过 {} / 失败 {}，当前文档 {} 篇，向量 {} 个",
        added, skipped, failed,
        kb_store.redis.zcard("index:kb_docs"), kb_store.point_count(),
    )
    print(f"SEED_RAG_DONE added={added} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()