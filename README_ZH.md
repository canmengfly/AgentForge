# AgentForge

**Agent Data Distillation Platform**

自托管的 AI 知识平台，让用户上传任意文档，通过语义向量搜索召回上下文，并通过 MCP 协议与 Claude Desktop / Claude Code 无缝集成。

[English](README.md) | [PyPI](https://pypi.org/project/agentf/) | [GitHub](https://github.com/canmengfly/AgentForge)

---

## 截图

<table>
  <tr>
    <td><img src="docs/screenshots/dashboard.png" alt="控制台" /></td>
    <td><img src="docs/screenshots/upload.png" alt="文档上传" /></td>
  </tr>
  <tr>
    <td align="center">控制台</td>
    <td align="center">文档上传</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/search.png" alt="语义搜索" /></td>
    <td><img src="docs/screenshots/agent-integration.png" alt="Agent 集成" /></td>
  </tr>
  <tr>
    <td align="center">语义搜索</td>
    <td align="center">Agent 集成</td>
  </tr>
</table>

---

## 功能特性

| 类别 | 详情 |
|---|---|
| **文档接入** | TXT、MD、HTML、PDF、DOCX，支持文件上传和文本粘贴 |
| **向量搜索** | ChromaDB（默认）余弦相似度，sentence-transformers 本地嵌入，无需 API Key |
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
┌─────────────────────────────────────────┐
│              FastAPI 应用                │
│  ┌──────────┐  ┌───────┐  ┌─────────┐  │
│  │  Pages   │  │  Auth │  │  Admin  │  │
│  │(Jinja2)  │  │  /me  │  │/api/adm │  │
│  └──────────┘  └───────┘  └─────────┘  │
│         │            │                  │
│  ┌──────▼────────────▼────────────────┐ │
│  │        向量存储外观层               │ │
│  │  chroma_vector_store（默认）        │ │
│  │  pg_vector_store    （可选）        │ │
│  └────────────────────────────────────┘ │
│         │                               │
│  ┌──────▼──────┐   ┌───────────────┐   │
│  │  ChromaDB   │   │  SQLite（用户 │   │
│  │  （文档）   │   │  + API Token）│   │
│  └─────────────┘   └───────────────┘   │
└─────────────────────────────────────────┘
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

`.env` 示例：

```env
DATA_DIR=/var/agentforge/data
JWT_SECRET=请替换为至少32字符的随机字符串
VECTOR_BACKEND=chroma
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
| POST | `/me/search` | 语义搜索 |

**搜索请求体：**
```json
{
  "query": "Python 是什么语言？",
  "collection": "notes",
  "top_k": 5
}
```

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
    main.py                # FastAPI 应用、生命周期、路由注册
    routes/
      auth_routes.py       # /auth/*
      admin.py             # /api/admin/*
      me.py                # /me/*（文档、搜索、API Token）
      config_export.py     # /export/*
      pages.py             # HTML 页面（Jinja2）
  core/
    config.py              # pydantic-settings 配置
    auth.py                # JWT + bcrypt + API Token 工具函数
    database.py            # SQLAlchemy SQLite 配置
    models.py              # User、APIToken ORM 模型
    deps.py                # FastAPI 依赖项（CurrentUser 等）
    embeddings.py          # sentence-transformers 模型加载
    document_processor.py  # 文件解析与文本分块
    vector_store.py        # 向量存储外观层
    chroma_vector_store.py # ChromaDB 后端
    pg_vector_store.py     # pgvector 后端（可选）
  mcp/
    server.py              # MCP stdio 服务
templates/                 # Jinja2 HTML 模板
  base.html
  login.html
  dashboard.html
  upload.html
  search_page.html
  export.html              # Agent 集成页
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
```

---

## 开发与测试

```bash
pytest tests/ -v
```

- 使用临时目录存放 ChromaDB 和 SQLite，不影响生产数据
- 确定性伪嵌入，无需下载模型
- Session 级别共享 app 和 HTTP 客户端

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
- 用户数据隔离在存储层强制执行，而非仅在 API 层。
- 管理员不能降级或删除自己的账号。
- 禁用的用户即使密码正确也无法登录。
