# API Reference

All endpoints accept and return JSON. Successful responses use HTTP 2xx status codes. Error responses follow the format:

```json
{"detail": "Error message"}
```

## Authentication

Two authentication methods are supported:

**Cookie (browser):** Set automatically after login via `POST /auth/login`. Sent by the browser on every request.

**API Token (programmatic):** Include in the `Authorization` header:
```http
Authorization: Bearer aft_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Auth Endpoints (`/auth/*`)

### `POST /auth/login`

Authenticate and receive a session cookie.

**Request:**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**Response:** `200 OK` with `Set-Cookie: access_token=...`
```json
{"message": "Login successful"}
```

---

### `POST /auth/logout`

Clear the session cookie.

**Response:** `200 OK`

---

### `GET /auth/me`

Return the current authenticated user's profile.

**Response:**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "role": "user",
  "is_active": true
}
```

---

## User Document Endpoints (`/me/*`)

### `GET /me/collections`

List all collections belonging to the current user.

**Response:**
```json
[
  {"name": "notes", "count": 42},
  {"name": "research", "count": 15}
]
```

---

### `POST /me/documents/text`

Add a plain text document to a collection.

**Request:**
```json
{
  "collection": "notes",
  "title": "My Note",
  "content": "Full text content here...",
  "metadata": {"tag": "optional"}
}
```

**Response:** `201 Created`
```json
{"doc_id": "abc123", "chunks": 3}
```

---

### `POST /me/documents/upload`

Upload a file (TXT, MD, HTML, PDF, DOCX).

**Request:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | file | The file to upload |
| `collection` | string | Target collection name |
| `title` | string | Optional: override document title |

**Response:** `201 Created`
```json
{"doc_id": "abc123", "chunks": 7, "title": "my-doc.pdf"}
```

---

### `GET /me/documents`

List documents in a collection.

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `collection` | *(required)* | Collection name |
| `limit` | `50` | Max documents to return |
| `offset` | `0` | Pagination offset |

**Response:**
```json
{
  "documents": [
    {"doc_id": "abc123", "title": "My Note", "chunks": 3, "created_at": "..."}
  ],
  "total": 1
}
```

---

### `DELETE /me/documents/{doc_id}`

Delete a document and all its chunks.

**Response:** `200 OK`
```json
{"deleted": "abc123"}
```

---

### `DELETE /me/collections/{name}`

Delete an entire collection and all its documents.

**Response:** `200 OK`
```json
{"deleted": "notes"}
```

---

### `GET /me/chunks`

List chunks with pagination.

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `collection` | *(required)* | Collection name |
| `doc_id` | *(optional)* | Filter by document |
| `limit` | `20` | Max chunks to return |
| `offset` | `0` | Pagination offset |

**Response:**
```json
{
  "chunks": [
    {
      "chunk_id": "xyz789",
      "doc_id": "abc123",
      "content": "...",
      "metadata": {}
    }
  ],
  "total": 42
}
```

---

### `POST /me/search`

Semantic search within a single collection.

**Request:**
```json
{
  "query": "transformer architecture",
  "collection": "research",
  "top_k": 5
}
```

**Response:**
```json
{
  "results": [
    {
      "chunk_id": "xyz789",
      "doc_id": "abc123",
      "title": "Attention Is All You Need",
      "content": "...",
      "score": 0.92,
      "metadata": {}
    }
  ]
}
```

---

### `POST /me/search/all`

Hybrid search across all of the user's collections (including synced data sources).

**Request:**
```json
{
  "query": "quarterly revenue by region",
  "top_k": 10
}
```

**Response:** Same format as `/me/search`.

---

## Data Source Endpoints (`/me/datasources`)

### `GET /me/datasources`

List all data sources for the current user.

**Response:**
```json
[
  {
    "id": 1,
    "name": "Company MySQL",
    "type": "mysql",
    "collection": "mysql-data",
    "sync_interval_minutes": 60,
    "last_synced_at": "2026-04-29T10:00:00Z",
    "status": "ok",
    "config": {
      "host": "db.example.com",
      "database": "production",
      "username": "reader",
      "password": "***"
    }
  }
]
```

Sensitive fields (`password`, `api_token`, `secret_key`, etc.) are always masked as `***` in responses.

---

### `POST /me/datasources`

Create a new data source.

**Request:**
```json
{
  "name": "Company MySQL",
  "type": "mysql",
  "collection": "mysql-data",
  "sync_interval_minutes": 60,
  "config": {
    "host": "db.example.com",
    "port": 3306,
    "database": "production",
    "username": "reader",
    "password": "s3cr3t",
    "row_limit": 5000
  }
}
```

**Response:** `201 Created` — full data source object with masked credentials.

---

### `GET /me/datasources/{id}`

Get a single data source.

**Response:** Full data source object with masked credentials.

---

### `PUT /me/datasources/{id}`

Update a data source. All fields are optional.

**Request:**
```json
{
  "sync_interval_minutes": 120,
  "config": {
    "row_limit": 10000
  }
}
```

**Response:** Updated data source object.

---

### `DELETE /me/datasources/{id}`

Delete a data source. The associated collection data is **not** automatically deleted.

**Response:** `200 OK`
```json
{"deleted": 1}
```

---

### `POST /me/datasources/{id}/test`

Test the connection without saving anything.

**Response:**
```json
{"ok": true}
```

or on failure:

```json
{"ok": false, "error": "Connection refused"}
```

---

### `POST /me/datasources/{id}/sync`

Trigger an immediate sync (runs in the background).

**Response:** `202 Accepted`
```json
{"status": "sync_started"}
```

---

## API Token Endpoints (`/me/tokens`)

### `GET /me/tokens`

List all API tokens for the current user.

**Response:**
```json
[
  {
    "id": 1,
    "name": "Claude Code",
    "prefix": "aft_abc...",
    "created_at": "2026-01-01T00:00:00Z",
    "last_used_at": "2026-04-29T09:00:00Z"
  }
]
```

---

### `POST /me/tokens`

Create a new API token. The plaintext token is returned **only once**.

**Request:**
```json
{"name": "Claude Code"}
```

**Response:** `201 Created`
```json
{
  "id": 2,
  "name": "Claude Code",
  "token": "aft_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

---

### `DELETE /me/tokens/{id}`

Delete an API token.

**Response:** `200 OK`

---

## Admin Endpoints (`/api/admin/*`)

All admin endpoints require an account with `role: "admin"`.

### `GET /api/admin/stats`

Platform-wide statistics.

**Response:**
```json
{
  "total_users": 5,
  "active_users": 4,
  "total_collections": 12,
  "total_chunks": 8420,
  "total_datasources": 3
}
```

---

### `GET /api/admin/users`

List users with optional filtering and pagination.

**Query parameters:**

| Parameter | Description |
|---|---|
| `q` | Search by username or email |
| `role` | Filter by role (`admin` or `user`) |
| `is_active` | Filter by active status (`true` or `false`) |
| `limit` | Max results (default: `50`) |
| `offset` | Pagination offset (default: `0`) |

---

### `POST /api/admin/users`

Create a new user.

**Request:**
```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "SecurePass123",
  "role": "user"
}
```

---

### `PUT /api/admin/users/{id}`

Update a user. All fields optional.

**Request:**
```json
{
  "email": "new@example.com",
  "role": "admin",
  "is_active": false
}
```

---

### `DELETE /api/admin/users/{id}`

Delete a user. Admins cannot delete their own account.

**Response:** `200 OK`

---

### `GET /api/admin/collections`

List all collections across the platform with owner information.

**Response:**
```json
[
  {
    "collection": "u1_notes",
    "owner_id": 1,
    "username": "alice",
    "count": 42
  }
]
```

---

## Export Endpoints (`/export/*`)

### `GET /export/mcp-config`

Download the MCP `claude_desktop_config.json` for the current user's API token.

**Query parameters:** `token_id=<id>`

### `GET /export/skill-yaml`

Download a Claude skill YAML definition for the current user.

**Query parameters:** `token_id=<id>`

---

## Error Codes

| Status | Meaning |
|---|---|
| `400` | Invalid request body or parameters |
| `401` | Not authenticated (missing or invalid token/cookie) |
| `403` | Forbidden (insufficient role) |
| `404` | Resource not found |
| `409` | Conflict (e.g. duplicate username) |
| `422` | Validation error (Pydantic schema) |
| `500` | Internal server error |
