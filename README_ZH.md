# AgentForge

**Agent Data Distillation Platform**

自托管的 AI 知识平台。上传文档或对接外部数据源，通过混合语义搜索（向量 + BM25）与可选的交叉编码器重排序召回上下文，并通过 MCP 协议与 Claude Desktop / Claude Code 无缝集成。

[English](README.md) | [PyPI](https://pypi.org/project/agentf/) | [GitHub](https://github.com/canmengfly/AgentForge)

---

## 截图

<table>
  <tr>
    <td><img src="docs/screenshots/dashboard.png" alt="控制台" /></td>
    <td><img src="docs/screenshots/datasources.png" alt="数据源" /></td>
  </tr>
  <tr>
    <td align="center">控制台</td>
    <td align="center">外部数据源</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/search.png" alt="混合搜索" /></td>
    <td><img src="docs/screenshots/agent-integration.png" alt="Agent 集成" /></td>
  </tr>
  <tr>
    <td align="center">混合搜索</td>
    <td align="center">Agent 集成</td>
  </tr>
</table>

---

## 功能特性

| 类别 | 详情 |
|---|---|
| **文档接入** | TXT、MD、HTML、PDF、DOCX，支持文件上传和文本粘贴 |
| **外部数据源** | 27 种连接器类型：对象存储、关系型数据库、OLAP、NoSQL、文档平台、代码仓库、企业云盘 |
| **混合搜索** | 向量余弦相似度 + BM25 重排序（结构化数据源） |
| **重排序器** | 可选交叉编码器精排（sentence-transformers） |
| **定时同步** | APScheduler 增量同步所有外部数据源 |
| **向量后端** | ChromaDB（默认）或 PostgreSQL + pgvector |
| **用户系统** | 管理员 + 普通用户角色，JWT httpOnly Cookie 认证 |
| **API Token** | 持久化 API Token（`aft_` 前缀），SHA-256 哈希存储，仅创建时可见一次 |
| **MCP 服务** | stdio 传输，暴露 5 个工具供 Claude 调用 |
| **Agent 集成** | MCP 配置生成、Skill YAML 下载、接口调用测试 |
| **Web UI** | Bulma CSS + Alpine.js，管理员控制台，用户文档管理页 |

---

## 架构概览

```
浏览器 / Claude Desktop / API 客户端
         │
         ▼
┌──────────────────────────────────────────────────┐
│                   FastAPI 应用                    │
│  ┌──────────┐  ┌───────┐  ┌──────────────────┐  │
│  │  Pages   │  │  Auth │  │  Admin / me/*    │  │
│  │(Jinja2)  │  │  /me  │  │  datasources     │  │
│  └──────────┘  └───────┘  └──────────────────┘  │
│                                │                 │
│  ┌─────────────────────────────▼───────────────┐ │
│  │             混合召回管道                     │ │
│  │  向量检索 → BM25 重排（SQL 类型）            │ │
│  │  → 交叉编码器精排（可选）→ Top-K             │ │
│  └─────────────────────────────────────────────┘ │
│                                │                 │
│  ┌─────────────────────────────▼───────────────┐ │
│  │           向量存储外观层                     │ │
│  │  chroma_vector_store（默认）                 │ │
│  │  pg_vector_store（可选 pgvector）            │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  APScheduler  ←  数据源连接器（27 种）        │ │
│  │  增量同步 → ParsedDocument → 分块入库         │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────────────┐   ┌──────────────────────────┐ │
│  │   ChromaDB   │   │  SQLite                  │ │
│  │  （文档）    │   │  （用户、Token、数据源）  │ │
│  └──────────────┘   └──────────────────────────┘ │
└──────────────────────────────────────────────────┘
         │
         ▼
  MCP stdio 服务  (src/mcp/server.py)
```

### 用户数据隔离

每个用户的文档存储在独立的 ChromaDB 集合中：`u{user_id}_{collection_name}`。命名空间前缀在服务端解析，用户 A 无法访问用户 B 的任何数据。

---

## 快速开始

### 前置条件

- Python 3.11+
- （可选）PostgreSQL + pgvector 扩展

### 安装

**方式一：PyPI 安装（推荐）**

```bash
pip install agentf
```

**方式二：源码安装**

```bash
git clone https://github.com/canmengfly/AgentForge.git
cd AgentForge
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 启动

```bash
agentf-api
```

打开 <http://localhost:8000>。首次启动自动创建默认管理员账号：

| 用户名 | 密码 |
|---|---|
| `admin` | `admin123` |

> **请在首次登录后立即修改管理员密码。**

---

## 外部数据源

AgentForge 支持 **27 种外部数据源类型**，可连接后定时同步，并与上传文档统一检索。

### 支持的连接器

| 类别 | 类型 |
|---|---|
| **对象存储** | 阿里云 OSS、Amazon S3、腾讯云 COS、华为云 OBS |
| **关系型数据库** | MySQL、PostgreSQL、Oracle、SQL Server、TiDB、OceanBase |
| **OLAP / 数仓** | Apache Doris、ClickHouse、Apache Hive、Snowflake |
| **搜索 / NoSQL** | Elasticsearch、MongoDB |
| **文档平台** | 飞书文档、钉钉文档、腾讯文档、Confluence、Notion、语雀 |
| **代码平台** | GitHub、GitLab |
| **企业云盘** | Microsoft SharePoint、Google Drive |

### 添加数据源

1. 在侧边栏进入**数据源**页面
2. 点击**新建数据源**，选择类型，填写连接参数
3. 点击**测试连接**验证凭证
4. 设置同步间隔（如 `30` 分钟）并保存
5. 调度器自动同步数据源，内容索引到指定集合后即可搜索

### 同步行为

- **全量同步**：首次运行时拉取全部内容
- **增量同步**：后续运行仅拉取新增或更新的内容（取决于数据源是否支持）
- 同步后的文档进入指定集合，立即可检索

---

## 混合搜索

搜索结果融合两种信号：

1. **向量相似度** — sentence-transformers 余弦距离，适用于所有集合
2. **BM25 重排序** — 词频排名，适用于结构化 SQL 数据源（MySQL、PostgreSQL、Oracle、SQL Server、TiDB、OceanBase、Doris、ClickHouse、Hive、Snowflake）

还可启用可选的**交叉编码器精排**，使用专用相关性模型进一步优化结果排序。

### 跨所有数据源统一搜索

```http
POST /me/search/all
Content-Type: application/json

{
  "query": "各地区季度营收",
  "top_k": 10
}
```

该接口跨越所有集合（上传文档和已同步的数据源）搜索，返回统一排序的结果列表。

---

## 配置参考

所有配置通过环境变量读取（支持 `.env` 文件）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `./data` | SQLite 数据库和 ChromaDB 文件根目录 |
| `CHROMA_PERSIST_DIR` | `{DATA_DIR}/chroma` | ChromaDB 持久化目录 |
| `JWT_SECRET` | *(必填)* | JWT 签名密钥（至少 32 字符） |
| `JWT_EXPIRE_MINUTES` | `10080` | Cookie Token 有效期（分钟，默认 7 天） |
| `VECTOR_BACKEND` | `chroma` | `chroma` 或 `pgvector` |
| `PG_VECTOR_URL` | `""` | 使用 pgvector 时的 PostgreSQL DSN |
| `EMBEDDING_DIM` | `384` | 嵌入向量维度（需与模型匹配） |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers 模型名 |
| `RERANKER_MODEL` | `""` | 交叉编码器模型名（空 = 禁用） |

`.env` 示例：

```env
DATA_DIR=/var/agentforge/data
JWT_SECRET=请替换为至少32字符的随机字符串
VECTOR_BACKEND=chroma
EMBEDDING_MODEL=all-MiniLM-L6-v2
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

---

## 认证方式

### Cookie（浏览器）

登录后服务端自动设置 httpOnly Cookie `access_token`，浏览器后续请求自动携带，无需手动处理。

### API Token（程序化访问）

1. 登录 Web UI，进入 **Agent 集成** 页面创建 Token
2. Token 格式：`aft_<32位随机字符>`，**仅在创建时显示一次**，请妥善保存
3. 请求时在 Header 中携带：

```http
Authorization: Bearer aft_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## API 参考

### 用户文档接口（`/me/*`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/me/collections` | 列出自己的集合 |
| POST | `/me/documents/text` | 添加文本文档 |
| POST | `/me/documents/upload` | 上传文件（TXT/MD/HTML/PDF/DOCX） |
| GET | `/me/documents` | 列出集合内文档 |
| DELETE | `/me/documents/{doc_id}` | 删除文档及其分块 |
| DELETE | `/me/collections/{name}` | 删除整个集合 |
| GET | `/me/chunks` | 列出分块（支持分页） |
| POST | `/me/search` | 在指定集合内语义搜索 |
| POST | `/me/search/all` | 跨所有集合混合搜索 |

**搜索请求体：**
```json
{
  "query": "Python 是什么语言？",
  "collection": "notes",
  "top_k": 5
}
```

### 数据源接口（`/me/datasources`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/me/datasources` | 列出自己的数据源 |
| POST | `/me/datasources` | 创建数据源 |
| GET | `/me/datasources/{id}` | 获取数据源详情 |
| PUT | `/me/datasources/{id}` | 更新数据源 |
| DELETE | `/me/datasources/{id}` | 删除数据源 |
| POST | `/me/datasources/{id}/test` | 测试连接 |
| POST | `/me/datasources/{id}/sync` | 手动触发同步 |

### API Token 接口（`/me/tokens`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/me/tokens` | 列出自己的 Token |
| POST | `/me/tokens` | 创建 Token（返回明文，仅一次） |
| DELETE | `/me/tokens/{id}` | 删除 Token |

### 管理员接口（`/api/admin/*`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/stats` | 平台统计数据 |
| GET | `/api/admin/users` | 用户列表（分页、可筛选） |
| POST | `/api/admin/users` | 创建用户 |
| PUT | `/api/admin/users/{id}` | 更新用户（角色/邮箱/密码/状态） |
| DELETE | `/api/admin/users/{id}` | 删除用户 |
| GET | `/api/admin/collections` | 列出全平台所有集合 |

---

## MCP 集成

MCP 服务通过 stdio 传输，由 Claude Desktop / Claude Code 按需唤起，**无需手动启动**。

### Claude Desktop

将以下配置合并到 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "agentf-mcp",
      "args": [],
      "env": {
        "AFT_API_BASE": "http://localhost:8000",
        "AFT_API_KEY": "aft_your_token_here"
      }
    }
  }
}
```

也可在 Web UI **Agent 集成** 页面自动生成此配置。

### Claude Code

在项目的 `.claude/settings.json` 中添加同样的 `mcpServers` 配置块。

### 可用 MCP 工具

| 工具 | 说明 |
|---|---|
| `search_knowledge` | 语义搜索知识库，返回相关文档分块 |
| `list_collections` | 列出所有文档集合及分块数量 |
| `add_text_document` | 向知识库添加文本文档 |
| `get_document_chunks` | 获取指定文档的所有分块 |
| `delete_document` | 删除文档及其所有分块 |

---

## 支持的文件类型

| 扩展名 | 解析器 |
|---|---|
| `.txt` | 纯文本 |
| `.md` | Markdown（提取纯文本） |
| `.html` / `.htm` | BeautifulSoup 提取正文 |
| `.pdf` | pdfplumber |
| `.docx` | python-docx |

---

## 项目结构

```
src/
  api/
    main.py                     # FastAPI 应用、生命周期、路由注册
    routes/
      auth_routes.py            # /auth/*
      admin.py                  # /api/admin/*
      me.py                     # /me/*（文档、搜索、API Token）
      datasources.py            # /me/datasources/*（数据源 CRUD + 同步）
      config_export.py          # /export/*
      pages.py                  # HTML 页面（Jinja2）
  core/
    config.py                   # pydantic-settings 配置
    auth.py                     # JWT + bcrypt + API Token 工具函数
    database.py                 # SQLAlchemy SQLite 配置
    models.py                   # User、APIToken、DataSource ORM 模型
    deps.py                     # FastAPI 依赖项（CurrentUser 等）
    embeddings.py               # sentence-transformers 模型加载
    document_processor.py       # 文件解析与文本分块
    vector_store.py             # 向量存储外观层
    chroma_vector_store.py      # ChromaDB 后端
    pg_vector_store.py          # pgvector 后端（可选）
    scheduler.py                # APScheduler 增量同步调度
    connectors/
      __init__.py
      oss_connector.py          # 阿里云 OSS
      s3_connector.py           # Amazon S3
      tencent_cos_connector.py  # 腾讯云 COS
      huawei_obs_connector.py   # 华为云 OBS
      sql_connector.py          # MySQL / PostgreSQL（共用）
      oracle_connector.py       # Oracle Database
      sqlserver_connector.py    # Microsoft SQL Server
      tidb_connector.py         # TiDB（MySQL 兼容）
      oceanbase_connector.py    # OceanBase（MySQL 兼容）
      doris_connector.py        # Apache Doris（MySQL 兼容）
      elasticsearch_connector.py
      mongodb_connector.py
      clickhouse_connector.py
      hive_connector.py
      snowflake_connector.py
      feishu_connector.py       # 飞书文档
      dingtalk_connector.py     # 钉钉文档
      tencent_docs_connector.py # 腾讯文档
      confluence_connector.py   # Atlassian Confluence
      notion_connector.py       # Notion
      yuque_connector.py        # 语雀
      github_connector.py       # GitHub 仓库
      gitlab_connector.py       # GitLab 仓库
      sharepoint_connector.py   # Microsoft SharePoint
      google_drive_connector.py # Google Drive
  mcp/
    server.py                   # MCP stdio 服务
templates/                      # Jinja2 HTML 模板
  base.html
  login.html
  dashboard.html
  search_page.html
  datasources.html              # 数据源管理 UI
  export.html                   # Agent 集成页
  chunks.html
  admin/
    index.html
    users.html
tests/
  conftest.py
  test_auth.py
  test_admin.py
  test_documents.py
  test_search.py
  test_e2e.py
  test_new_datasources.py       # S3、Doris、ES、MongoDB、ClickHouse、Hive
  test_extended_datasources.py  # 14 个新连接器
docs/
  datasources.md                # 连接器配置参考
  hybrid-search.md              # 混合召回架构说明
  api-reference.md              # 完整 REST API 参考
  deployment.md                 # 生产部署指南
  development.md                # 开发与测试指南
```

---

## 开发与测试

```bash
pytest tests/ -v
```

- 使用临时目录存放 ChromaDB 和 SQLite，不影响生产数据
- 确定性伪嵌入，无需下载模型
- 可选连接器依赖在 `sys.modules` 层打桩，无需真实凭证

---

## pgvector 后端（可选）

如需使用 PostgreSQL 代替 ChromaDB：

1. 安装 pgvector 扩展：
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. 设置环境变量：
   ```env
   VECTOR_BACKEND=pgvector
   PG_VECTOR_URL=postgresql://user:pass@localhost/agentforge
   ```
3. 启动时自动创建数据表并建立 HNSW 余弦索引。

---

## 安全说明

- JWT Token 存储在 httpOnly Cookie 中，JavaScript 无法访问。
- 密码使用 bcrypt（cost factor 12）哈希存储。
- API Token 以 SHA-256 哈希存储，明文仅在创建时返回一次。
- 数据源凭证（密码、API Key、Secret）在所有 API 响应中以 `***` 掩码展示。
- 用户数据隔离在存储层强制执行，而非仅在 API 层。
- 管理员不能降级或删除自己的账号。
- 禁用的用户即使密码正确也无法登录。
