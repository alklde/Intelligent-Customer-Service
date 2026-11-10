# 下载的初始知识语料

`ecom_faq.jsonl` 由 `scripts/seed_rag.py` 自动下载并缓存，来源：

- 数据集：`QingshanAI/ecom-customer-service-synthetic`（电商客服训练语料，992 条）
- 平台：ModelScope（魔搭）
- 许可：Apache License 2.0
- 字段：`scene`（场景）、`user`（用户问题）、`bot`（客服回复）、`tone`（语气）

该语料为 AI 合成数据，不含真实用户隐私信息；灌库时按场景轮询采样，生成
「用户问题 / 客服回复」知识条目。离线环境可删除本目录，脚本会回退为仅使用
`proj1_rag/knowledge/*.md` 本地制度文档。