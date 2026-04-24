# AgentForge

**Agent Data Distillation Platform**

A self-hosted AI knowledge platform. Upload any document, retrieve context via semantic vector search, and integrate seamlessly with Claude Desktop / Claude Code through the MCP protocol.

[中文文档](README_ZH.md) | [PyPI](https://pypi.org/project/agentf/) | [GitHub](https://github.com/canmengfly/AgentForge)

---

## Screenshots

<table>
  <tr>
    <td><img src="docs/screenshots/dashboard.png" alt="Dashboard" /></td>
    <td><img src="docs/screenshots/upload.png" alt="Upload Documents" /></td>
  </tr>
  <tr>
    <td align="center">Dashboard</td>
    <td align="center">Document Upload</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/search.png" alt="Semantic Search" /></td>
    <td><img src="docs/screenshots/agent-integration.png" alt="Agent Integration" /></td>
  </tr>
  <tr>
    <td align="center">Semantic Search</td>
    <td align="center">Agent Integration</td>
  </tr>
</table>

---

## Features

| Category | Details |
|---|---|
| **Document Ingestion** | TXT, MD, HTML, PDF, DOCX — file upload or paste text |
| **Vector Search** | ChromaDB (default) cosine similarity, local sentence-transformers embeddings, no API key needed |
| **User System** | Admin + regular user roles, JWT httpOnly Cookie authentication |
| **API Tokens** | Persistent API tokens (`aft_` prefix), SHA-256 hashed, shown only once at creation |
| **MCP Server** | stdio transport, exposes 5 tools for Claude to call |
| **Agent Integration** | MCP config generation, Skill YAML download, API testing console |
| **Web UI** | Bulma CSS + Alpine.js, admin console, user document management |

---

## Architecture

```
Browser / Claude Desktop / API Client
         │
         ▼
┌─────────────────────────────────────────┐
│              FastAPI App                 │
│  ┌──────────┐  ┌───────┐  ┌─────────┐  │
│  │  Pages   │  │  Auth │  │  Admin  │  │
│  │(Jinja2)  │  │  /me  │  │/api/adm │  │
│  └──────────┘  └───────┘  └─────────┘  │
│         │            │                  │
│  ┌──────▼────────────▼────────────────┐ │
│  │         Vector Store Facade        │ │
│  │  chroma_vector_store (default)     │ │
│  │  pg_vector_store     (optional)    │ │
│  └────────────────────────────────────┘ │
│         │                               │
│  ┌──────▼──────┐   ┌───────────────┐   │
│  │  ChromaDB   │   │  SQLite       │   │
│  │ (documents) │   │ (users+tokens)│   │
│  └─────────────┘   └───────────────┘   │
└─────────────────────────────────────────┘
         │
         ▼
  MCP stdio server  (src/mcp/server.py)
```

### User Data Isolation

Each user's documents are stored in a dedicated ChromaDB collection: `u{user_id}_{collection_name}`. The namespace prefix is enforced server-side — user A cannot access user B's data.

---

## Quick Start

### Requirements

- Python 3.11+
- (Optional) PostgreSQL + pgvector extension

### Installation

**Option 1 — PyPI (recommended)**

```bash
pip install agentf
```

**Option 2 — From source**

```bash
git clone https://github.com/canmengfly/AgentForge.git
cd AgentForge
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Start

```bash
agentf-api
```

Open <http://localhost:8000>. A default admin account is created on first launch:

| Username | Password |
|---|---|
| `admin` | `admin123` |

> **Change the admin password immediately after first login.**

---

## Configuration

All settings are read from environment variables (`.env` file supported):

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `./data` | Root directory for SQLite and ChromaDB files |
| `CHROMA_PERSIST_DIR` | `{DATA_DIR}/chroma` | ChromaDB persistence directory |
| `JWT_SECRET` | *(required)* | JWT signing secret (at least 32 characters) |
| `JWT_EXPIRE_MINUTES` | `10080` | Cookie token lifetime (minutes, default 7 days) |
| `VECTOR_BACKEND` | `chroma` | `chroma` or `pgvector` |
| `PG_VECTOR_URL` | `""` | PostgreSQL DSN when using pgvector |
| `EMBEDDING_DIM` | `384` | Embedding vector dimension (must match model) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model name |

`.env` example:

```env
DATA_DIR=/var/agentforge/data
JWT_SECRET=replace-with-a-random-32-char-string
VECTOR_BACKEND=chroma
```

---

## Authentication

### Cookie (Browser)

After login, the server sets an httpOnly Cookie `access_token`. The browser sends it automatically on every subsequent request.

### API Token (Programmatic Access)

1. Log in to the Web UI and go to **Agent Integration** to create a token
2. Token format: `aft_<32 random characters>` — **shown only once**, save it securely
3. Include in request headers:

```http
Authorization: Bearer aft_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## API Reference

### User Document Endpoints (`/me/*`)

| Method | Path | Description |
|---|---|---|
| GET | `/me/collections` | List your collections |
| POST | `/me/documents/text` | Add a text document |
| POST | `/me/documents/upload` | Upload a file (TXT/MD/HTML/PDF/DOCX) |
| GET | `/me/documents` | List documents in a collection |
| DELETE | `/me/documents/{doc_id}` | Delete a document and its chunks |
| DELETE | `/me/collections/{name}` | Delete an entire collection |
| GET | `/me/chunks` | List chunks (paginated) |
| POST | `/me/search` | Semantic search |

**Search request body:**
```json
{
  "query": "What is a transformer model?",
  "collection": "notes",
  "top_k": 5
}
```

### API Token Endpoints (`/me/tokens`)

| Method | Path | Description |
|---|---|---|
| GET | `/me/tokens` | List your tokens |
| POST | `/me/tokens` | Create a token (plaintext returned once) |
| DELETE | `/me/tokens/{id}` | Delete a token |

### Admin Endpoints (`/api/admin/*`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/stats` | Platform statistics |
| GET | `/api/admin/users` | User list (paginated, filterable) |
| POST | `/api/admin/users` | Create a user |
| PUT | `/api/admin/users/{id}` | Update user (role/email/password/status) |
| DELETE | `/api/admin/users/{id}` | Delete a user |
| GET | `/api/admin/collections` | List all collections across the platform |

---

## MCP Integration

The MCP server uses stdio transport and is launched on demand by Claude Desktop / Claude Code — **no manual startup required**.

### Claude Desktop

Merge the following into `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

This config can also be auto-generated from the **Agent Integration** page in the Web UI.

### Claude Code

Add the same `mcpServers` block to your project's `.claude/settings.json`.

### Available MCP Tools

| Tool | Description |
|---|---|
| `search_knowledge` | Semantic search, returns ranked document chunks |
| `list_collections` | List all collections and their chunk counts |
| `add_text_document` | Add a text document to the knowledge base |
| `get_document_chunks` | Retrieve all chunks of a specific document |
| `delete_document` | Delete a document and all its chunks |

---

## Supported File Types

| Extension | Parser |
|---|---|
| `.txt` | Plain text |
| `.md` | Markdown (plain text extracted) |
| `.html` / `.htm` | BeautifulSoup body extraction |
| `.pdf` | pdfplumber |
| `.docx` | python-docx |

---

## Project Structure

```
src/
  api/
    main.py                # FastAPI app, lifecycle, route registration
    routes/
      auth_routes.py       # /auth/*
      admin.py             # /api/admin/*
      me.py                # /me/* (documents, search, API tokens)
      config_export.py     # /export/*
      pages.py             # HTML pages (Jinja2)
  core/
    config.py              # pydantic-settings configuration
    auth.py                # JWT + bcrypt + API token utilities
    database.py            # SQLAlchemy SQLite setup
    models.py              # User, APIToken ORM models
    deps.py                # FastAPI dependencies (CurrentUser, etc.)
    embeddings.py          # sentence-transformers model loader
    document_processor.py  # File parsing and text chunking
    vector_store.py        # Vector store facade
    chroma_vector_store.py # ChromaDB backend
    pg_vector_store.py     # pgvector backend (optional)
  mcp/
    server.py              # MCP stdio server
templates/                 # Jinja2 HTML templates
  base.html
  login.html
  dashboard.html
  upload.html
  search_page.html
  export.html              # Agent Integration page
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

## Development & Testing

```bash
pytest tests/ -v
```

- Temporary directories for ChromaDB and SQLite — no impact on production data
- Deterministic dummy embeddings — no model download needed
- Session-scoped shared app and HTTP client

---

## pgvector Backend (Optional)

To use PostgreSQL instead of ChromaDB:

1. Install the pgvector extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. Set environment variables:
   ```env
   VECTOR_BACKEND=pgvector
   PG_VECTOR_URL=postgresql://user:pass@localhost/agentforge
   ```
3. The table and HNSW cosine index are created automatically on startup.

---

## Security

- JWT tokens are stored in httpOnly Cookies — inaccessible to JavaScript.
- Passwords are hashed with bcrypt (cost factor 12).
- API tokens are stored as SHA-256 hashes; plaintext is returned only once at creation.
- User data isolation is enforced at the storage layer, not just the API layer.
- Admins cannot demote or delete their own account.
- Disabled users cannot log in even with the correct password.
