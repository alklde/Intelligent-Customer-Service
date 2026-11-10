# 智能客服系统（Intelligent Customer Service）

基于 **FastAPI + LangGraph + LangChain + Qdrant + Redis + Vue 3** 构建的 Agentic 智能客服与人工坐席协同系统。覆盖 **客户、客服、管理员** 三种角色，实现「AI 知识库问答 → 转人工 → 坐席接入 → 实时回复 → 工单闭环 → 评测回归」的完整业务链路，并具备账号鉴权、图形验证码、角色隔离、历史会话、知识库管理与多标签页并行等能力。

---

## 功能特性

### 客户侧
- 账号密码 + 图形验证码登录（bcrypt 加密存储，连续失败锁定）
- 智能客服多轮对话：常见寒暄使用预设话术，业务问题由大模型严格依据知识库作答，**无命中时明确告知并建议转人工，不编造答案**
- 一键转人工：不新开会话，原会话追加「已处理，正在等待人工客服介入」并自动进入客服待接入队列
- 人工回复通过 SSE 实时出现在聊天框，支持刷新/切换页面后恢复
- 历史会话列表：按最近活动排序，点击即可恢复完整对话
- 我的申请：查看工单号、包裹单号、处理状态与接单客服工号

### 客服侧
- 工号 + 登录密钥 + 图形验证码登录
- 待接入队列自动热刷新（2 秒），转人工会话自动出现，无需手动刷新
- 原子抢占接入：同一会话仅允许一名客服接入，并发接入返回 409
- 接入即自动发送预设问候语，客户实时收到
- 聊天框中客服本人消息靠右、用户与 AI 消息靠左
- 「我的会话」历史列表，切换页面后自动恢复当前会话
- **知识库检索仅在本人处理中的会话内开放**，检索结果可一键填入回复
- 工单管理、运营统计、评测与护栏平台

### 管理员
- 管理员为客服角色的一种，从客服登录页登录
- 首次部署时在客服登录页初始化管理员工号与密钥
- 数据库管理：创建/停用客户与客服账号、重置密码与密钥
- 知识库管理：文档列表、手动录入、选择 `.md/.txt` 文件、删除、重建索引（仅管理员可见）
- 全部列表热刷新，无需点击刷新

### 系统能力
- 角色隔离：客户与客服界面互不可访问，后端按令牌角色强制校验（401 / 403）
- 多标签页并行：登录态与活动会话保存在 `sessionStorage`，刷新保持、新标签页需重新登录、多页互不影响
- 知识库：Redis 为文档事实源，Qdrant 为向量索引；文档清洗、去重、分块、双写；索引丢失重启自动重建
- 评测闭环：护栏检测（死循环 / 越权）、相似度评测、badcase 自动沉淀

---

## 技术栈

| 层次 | 技术 |
|---|---|
| Web 框架 | FastAPI 0.136.3、Uvicorn 0.48.0 |
| Agent 编排 | LangChain 1.4.0、LangGraph 1.2.11 |
| 模型接入 | OpenAI 兼容协议（Ollama / vLLM），Chat + Embedding |
| 向量库 | Qdrant（`qdrant-client` 1.20.0） |
| 会话存储 | Redis 5.2.1（会话 / 队列 / 工单 / 账号 / 知识库文档） |
| 认证安全 | bcrypt 5.0.0、Pillow 12.2.0（图形验证码） |
| 日志 | Loguru 0.7.3 |
| 前端 | Vue 3.5、Vue Router 4、Vite 6（无 UI 组件库，手写深色设计系统） |
| 运行环境 | Python 3.12+、Node.js 18+ / pnpm |

---

## 系统架构

```
                       ┌────────────────────────────────────────┐
                       │          Ollama / vLLM                 │
                       │  Chat 模型 + nomic-embed-text 向量模型 │
                       └──────────────────▲─────────────────────┘
                                          │ OpenAI 兼容接口
 ┌──────────────┐      ┌──────────────────┴─────────────────────┐
 │   Qdrant     │◄─────┤           proj1_rag (:8001)             │
 │  向量索引     │      │ 知识库文档管理 / 混合检索 / 严格接地生成 │
 └──────▲───────┘      └──────────────▲──────────────────────────┘
        │                             │ 内部调用（检索/生成）
 ┌──────┴───────┐      ┌──────────────┴───────────┐   ┌────────────────────┐
 │    Redis     │◄────►│ proj2_customer_service   │   │ proj3_eval_platform │
 │ 会话/队列/工单 │      │ (:8002) 客户侧对话/鉴权   │◄──│ (:8003) 评测与护栏   │
 │ 账号/知识库    │      └──────────────▲───────────┘   └────────────────────┘
 └──────▲───────┘                     │
        │              ┌──────────────┴───────────┐
        └─────────────►│ proj4_admin (:8004)       │
                       │ 客服工作台 / 知识库检索 /  │
                       │ 账号与知识库管理           │
                       └──────────────▲───────────┘
                                      │ HTTP / SSE
                       ┌──────────────┴───────────┐
                       │ frontend (:5173)         │
                       │ 客户端 / 客服端 / 管理端  │
                       └──────────────────────────┘
```

---

## 目录结构

```
ai_agent_suite/
├── config.py                   # 全局配置（pydantic-settings）
├── run_all.py                  # 一键启动四个后端服务（优雅退出）
├── requirements.txt            # 锁定依赖版本
├── docker-compose.yml          # Qdrant / Redis / 四个 FastAPI 服务
├── core/                       # 公共组件
│   ├── auth.py                 # 账号、验证码、令牌、管理员初始化
│   ├── auth_deps.py            # FastAPI 角色校验依赖
│   ├── exceptions.py           # 统一异常
│   ├── llm_factory.py          # Chat / Embedding 工厂
│   ├── logger.py               # Loguru 配置
│   └── redis_client.py         # Redis 同步/异步工厂
├── proj1_rag/                  # Agentic RAG 知识库
│   ├── kb.py                   # 文档清洗/去重/分块/向量索引/检索
│   ├── nodes.py / graph.py     # 检索、打分、生成、幻觉校验
│   ├── api.py                  # 知识库管理 / 会话内检索 / 调试查询
│   └── knowledge/              # 初始知识文档 + 开源语料缓存
├── proj2_customer_service/     # 客户侧智能客服
│   ├── store.py                # 会话状态机 + Redis 存储（唯一写入口）
│   ├── nodes.py / graph.py     # 意图路由、知识库接地问答、工具熔断
│   ├── tools.py                # query_order / create_ticket
│   ├── auth_router.py          # 客户登录
│   ├── applications.py         # 我的申请
│   └── api.py                  # /chat、SSE、历史会话
├── proj3_eval_platform/        # 评测与护栏
│   ├── dataset.jsonl           # 评测集（含 badcase 沉淀）
│   ├── guardrails.py           # 死循环 / 越权检测
│   ├── evaluator.py            # 评测流水线与报告
│   └── api.py
├── proj4_admin/                # 客服工作台后台
│   ├── sessions.py             # 队列 / 接入 / 回复 / 关闭 / 历史
│   ├── tickets.py              # 工单管理
│   ├── auth_router.py          # 客服登录
│   ├── admin_db.py             # 管理员账号管理 / 初始化
│   └── api.py
├── scripts/
│   ├── seed_accounts.py        # 初始化管理员 / 演示客户 / 演示客服
│   └── seed_rag.py             # 下载开源语料并入库（清洗/去重/分块/向量化）
└── frontend/                   # Vue 3 + Vite 双端控制台
    ├── src/auth.js             # 登录态与角色判定（sessionStorage）
    ├── src/api.js              # 请求封装（Bearer、401 统一处理）
    ├── src/router.js           # 双端路由 + 角色守卫
    ├── src/layouts/            # 客户 / 客服 / 登录布局
    └── src/views/              # 登录、对话、历史、工作台、工单、统计、知识库管理、数据库管理
```

---

## 快速开始

### 1. 前置依赖
- Python 3.12+
- Node.js 18+ 与 pnpm
- Docker（Qdrant / 可选 Redis）
- Ollama，本地已拉取 Chat 与 Embedding 模型

### 2. 启动中间件

```bash
docker compose up -d qdrant
# 若宿主机已有 Redis（默认 6379），可直接复用；否则启动 compose 中的 redis（映射 6381）
```

### 3. 准备模型

```bash
ollama pull qwen2.5:7b          # 也可使用其他支持 tool calling 的模型
ollama pull nomic-embed-text
```

项目的 Embedding 调用已自动添加 `search_document:` / `search_query:` 前缀。

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 初始化数据

```bash
python scripts/seed_accounts.py    # 管理员 / 演示客服 / 演示客户（幂等）
python scripts/seed_rag.py         # 本地制度文档 + ModelScope 开源语料入库
# 结构升级或需要全量重建时：
# python scripts/seed_rag.py --reset
```

### 6. 启动后端

```bash
python run_all.py                  # 预检 + 并行启动 4 个服务
python run_all.py --skip-check     # 跳过预检
python run_all.py --check          # 仅预检
```

| 服务 | 地址 |
|---|---|
| 知识库 API | http://localhost:8001 |
| 客户侧客服 API | http://localhost:8002 |
| 评测与护栏 API | http://localhost:8003 |
| 客服工作台后台 | http://localhost:8004 |

### 7. 启动前端

```bash
cd frontend
pnpm install
pnpm dev        # http://localhost:5173
pnpm build      # 生产构建
```

Vite 已配置代理：`/api/rag → 8001`、`/api/cs → 8002`、`/api/eval → 8003`、`/api/admin → 8004`。

---

## 演示账号

| 角色 | 登录入口 | 账号 | 凭据 |
|---|---|---|---|
| 客户 | `/login` | `zhangsan` / `lisi` | `123456` |
| 客服 | `/staff/login` | `agent001` / `agent002` | `Agent@123456` |
| 管理员 | `/staff/login` | `admin001` | `Admin@123456` |

> 初始化管理员的引导密钥为 `ADMIN_BOOTSTRAP_KEY`（默认 `SUITE-BOOTSTRAP-2026`）。以上账号仅用于演示，生产环境请立即修改。

---

## 页面与权限

| 路径 | 角色 | 说明 |
|---|---|---|
| `/login` | 客户 | 客户登录（图形验证码） |
| `/service` | 客户 | 在线客服 + 历史会话 |
| `/my-applications` | 客户 | 我的申请（包裹单号 / 状态 / 接单客服） |
| `/staff/login` | 客服 / 管理员 | 客服登录（工号 + 密钥 + 验证码） |
| `/staff/workbench` | 客服 / 管理员 | 待接入队列 / 我的会话 / 知识库检索 |
| `/staff/tickets` | 客服 / 管理员 | 工单管理 |
| `/staff/dashboard` | 客服 / 管理员 | 运营统计 |
| `/staff/eval` | 客服 / 管理员 | 评测与护栏 |
| `/staff/knowledge` | 管理员 | 知识库管理 |
| `/staff/database` | 管理员 | 数据库管理（账号） |

路由守卫与后端角色校验双重隔离：未登录跳转对应登录页，跨角色访问一律拒绝。

---

## 核心业务流程

1. 客户登录后发起咨询，AI 先匹配预设话术，其余问题执行「混合检索 → 相关性过滤 → 严格接地生成 → 幻觉校验」。
2. 知识库无命中或用户明确要求时，原会话追加「已处理，正在等待人工客服介入」，会话进入 `pending_human`。
3. 客服工作台待接入列表自动出现该会话（2 秒热刷新），客服点击「接入会话」原子抢占。
4. 接入后系统自动发送预设问候语，工单回填接单工号并进入 `processing`。
5. 客服可在会话内检索知识库（仅限本人 `human_handling` 会话），回复通过 SSE 实时送达客户。
6. 关闭会话时工单同步为 `resolved`；可标记 badcase 自动沉淀至评测集。

---

## 配置说明

配置支持环境变量或根目录 `.env` 覆盖（大小写不敏感）。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | OpenAI 兼容接口地址 |
| `LLM_API_KEY` | `ollama` | 本地服务占位密钥 |
| `LLM_MODEL` | `qwen2.5:7b` | Chat 模型 |
| `LLM_TEMPERATURE` | `0.0` | 采样温度 |
| `LLM_REQUEST_TIMEOUT` | `60.0` | LLM 请求超时（秒） |
| `EMBEDDING_MODEL` | `nomic-embed-text` | 向量模型 |
| `EMBEDDING_DIM` | `768` | 向量维度 |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 地址 |
| `QDRANT_COLLECTION` | `rag_knowledge_base` | 集合名 |
| `QDRANT_TOP_K` | `4` | 检索 Top-K |
| `REDIS_URL` | `redis://localhost:6379/1` | Redis 连接（db 1） |
| `AUTH_TOKEN_TTL_CUSTOMER` | `86400` | 客户令牌有效期（秒） |
| `AUTH_TOKEN_TTL_STAFF` | `43200` | 客服令牌有效期（秒） |
| `CAPTCHA_TTL` | `120` | 图形验证码有效期（秒，一次性） |
| `LOGIN_MAX_FAILURES` | `5` | 连续登录失败上限 |
| `LOGIN_LOCK_SECONDS` | `900` | 锁定窗口（秒） |
| `ADMIN_BOOTSTRAP_KEY` | `SUITE-BOOTSTRAP-2026` | 初始化管理员引导密钥 |
| `KB_CHUNK_SIZE` | `420` | 知识库分块字符数 |
| `KB_CHUNK_OVERLAP` | `60` | 分块重叠字符数 |
| `KB_MIN_CHARS` / `KB_MAX_CHARS` | `20` / `50000` | 文档正文长度限制 |
| `GRADE_THRESHOLD` | `0.7` | 文档相关性打分下限 |
| `HALLUCINATION_THRESHOLD` | `0.3` | 幻觉分数上限 |
| `MAX_GENERATION_RETRIES` | `2` | 幻觉重试上限 |
| `TOOL_TIMEOUT` | `3.0` | 工具执行超时（秒） |
| `MAX_TOOL_FAILURES` | `3` | 工具失败上限，达上限转人工 |

---

## API 概览

### 认证
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `:8002/auth/captcha` | 客户图形验证码 |
| POST | `:8002/auth/login` | 客户登录 |
| GET | `:8004/auth/captcha` | 客服图形验证码 |
| POST | `:8004/auth/login` | 客服登录 |
| POST | `/auth/logout` | 登出（撤销令牌） |
| GET | `/auth/me` | 当前身份 |

### 客户侧（:8002，客户令牌）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/chat` | 会话化对话（`user_id` 以令牌身份覆盖） |
| GET | `/chat/stream?session_id=&last_id=&token=` | SSE 实时消息流 |
| GET | `/my/sessions` | 历史会话列表 |
| GET | `/my/sessions/{id}` | 历史会话详情（校验归属） |
| GET | `/my/tickets` | 我的申请 |

### 客服侧（:8004，客服令牌）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/sessions/pending` | 待接入队列 |
| GET | `/sessions/history` | 我处理过的会话 |
| GET | `/sessions/{id}` | 会话详情 |
| POST | `/sessions/{id}/claim` | 接入（自动问候） |
| POST | `/sessions/{id}/reply` | 人工回复 |
| POST | `/sessions/{id}/close` | 关闭 / 转回 AI |
| GET/PATCH | `/tickets`、`/tickets/{id}` | 工单列表 / 流转 |
| GET | `/stats/today` | 当日统计 |

### 管理员（:8004，admin 令牌）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/status` | 初始化状态 |
| POST | `/admin/init` | 首次初始化管理员 |
| GET/POST/PATCH | `/admin/users`、`/admin/users/{id}` | 客户账号管理 |
| GET/POST/PATCH | `/admin/agents`、`/admin/agents/{id}` | 客服账号管理 |

### 知识库（:8001）
| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/kb/documents` | admin | 文档列表 |
| GET | `/kb/documents/{id}` | admin | 文档详情 |
| POST | `/kb/documents` | admin | 新增文档（清洗/去重/分块/向量化） |
| DELETE | `/kb/documents/{id}` | admin | 删除文档与向量 |
| POST | `/kb/reindex` | admin | 全量重建索引 |
| POST | `/kb/search` | staff | 会话内检索（限本人 `human_handling`） |
| POST | `/query` | admin | 调试查询 |

### 评测与护栏（:8003，客服令牌）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/evaluate` | 全量评测并返回报告 |
| POST | `/guardrails/check` | 死循环 / 越权检测 |

---

## 知识库设计

- **文档事实源**：Redis `kb:doc:{id}`；**向量索引**：Qdrant，可随时重建。
- **入库流程**：规范化清洗 → 标题/长度校验 → SHA-256 去重 → 420 字分块（重叠 60）→ Embedding → Redis/Qdrant 双写。
- **索引一致性**：向量 ID 由 `doc_id + 分块序号` 确定性生成；删除文档同步清理全部向量。
- **重启不丢**：Qdrant 持久化卷 + 启动自检；索引为空时自动从 Redis 文档重建。
- **检索**：向量相似度 + IDF 关键词混合召回，避免小模型嵌入对长文档召回不稳定。
- **回答约束**：严格提示词 + 幻觉校验 + 覆盖率兜底；无依据时返回固定无信息话术，禁止编造。
- **访问控制**：客户不可见；管理员可维护；客服仅能在本人处理中的会话内检索。

---

## 数据模型（Redis db 1）

| Key | 类型 | 用途 |
|---|---|---|
| `session:{id}` | Hash | 会话元数据（状态 / 客户 / 工号 / 标题 / 摘要） |
| `session:{id}:messages` | Stream | 消息流（role / content / source / ts） |
| `queue:pending` | ZSet | 待接入队列（优先级 + 时间） |
| `index:user_sessions:{user_id}` | ZSet | 客户历史会话 |
| `index:agent_sessions:{employee_id}` | ZSet | 客服处理记录 |
| `ticket:{id}` | Hash | 工单（客户 / 包裹单号 / 接单客服 / 状态） |
| `index:user_tickets:{user_id}` / `index:agent_tickets:{id}` | ZSet | 工单索引 |
| `auth:user:{id}` / `auth:agent:{employee_id}` | Hash | 账号（bcrypt 哈希，接口脱敏） |
| `auth:token:{token}` | Hash | 登录令牌（TTL） |
| `auth:captcha:{id}` | String | 验证码答案（120s，一次性） |
| `kb:doc:{id}` / `kb:doc_hash:{sha}` | Hash / String | 知识库文档 / 内容去重索引 |
| `index:kb_docs` | ZSet | 知识库文档列表 |
| `stats:{YYYYMMDD}` | Hash | 运营统计 |

---

## 安全设计

- 密码与客服密钥仅存 bcrypt 哈希，响应不返回敏感字段
- 图形验证码一次性、120 秒过期，剔除易混淆字符
- 不透明令牌存 Redis，登出即撤销；SSE 通过查询参数携带令牌
- 连续失败 5 次锁定 15 分钟，防暴力破解
- 后端角色依赖是唯一裁决点，前端守卫仅改善体验
- 会话归属校验：客户只能访问自己的会话与工单；客服工号以令牌为准
- 多标签页登录态隔离（`sessionStorage`），关闭标签页即失去令牌入口

---

## 验证情况

- 账号：验证码、登录、锁定、令牌、管理员初始化与账号 CRUD
- 权限：未登录 401；客户/客服跨角色 403；管理员专属接口 403
- 会话：转人工、接入、自动问候、SSE 实时回复、关闭、历史恢复
- 知识库：文档去重 409、过短 400、删除、重建；重启后 72 篇文档 / 72 个向量不变；删除集合后重启自动重建
- 对话：预设话术、知识库命中回答、无关问题固定无信息话术
- 评测：6 个用例（含 1 条 badcase），护栏正确识别越权
- 浏览器端：双标签页并行登录互不影响、刷新保持、客服消息靠右、人工回复实时同步

---

## 常见问题

1. **Embedding 模型缺失**：RAG 检索会降级为空。请确认 `nomic-embed-text` 已拉取。
2. **Redis 端口冲突**：代码默认连 `localhost:6379/1`；compose 中 Redis 映射到 6381 仅作备用，需同步修改 `REDIS_URL`。
3. **Qdrant 版本告警**：客户端与服务端大版本不一致时会出现兼容性提示，不影响本项目使用。
4. **Mock 工具超时**：`query_order` 有约 30% 概率模拟超时，用于演示 3 秒熔断与失败转人工。
5. **修改分块参数**：调整 `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` 后需在管理页「重建索引」或执行 `seed_rag.py --reset`。
6. **SSE 令牌**：EventSource 无法自定义请求头，`/chat/stream` 通过 `?token=` 携带令牌。
7. **转人工关键词**：`intent_router` 对「转人工 / 人工客服」等做关键词短路，避免小模型误判为建单。
8. **默认账号**：仅用于演示，生产部署请立即修改管理员、客服密钥与客户密码。