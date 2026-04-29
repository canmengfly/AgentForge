# Development Guide

---

## Setup

```bash
git clone https://github.com/canmengfly/AgentForge.git
cd AgentForge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Running Tests

```bash
pytest tests/ -v
```

The test suite requires no external services:

- **ChromaDB and SQLite** use temporary directories created per-session
- **Embeddings** use a deterministic dummy model — no model download needed
- **Optional connector dependencies** (boto3, pymongo, elasticsearch, etc.) are patched at the `sys.modules` level — no real credentials needed

### Running a specific test file

```bash
pytest tests/test_extended_datasources.py -v
```

### Running with coverage

```bash
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

---

## Project Layout

```
src/
  api/
    main.py              # App factory, lifespan, router registration
    routes/
      auth_routes.py     # Login/logout/me
      admin.py           # Admin CRUD
      me.py              # User documents, search, tokens
      datasources.py     # Data source CRUD + sync trigger
      config_export.py   # MCP config / Skill YAML download
      pages.py           # Jinja2 HTML page routes
  core/
    config.py            # Settings (pydantic-settings)
    auth.py              # JWT, bcrypt, API token helpers
    database.py          # SQLAlchemy engine + session
    models.py            # ORM models + DataSourceType enum
    deps.py              # FastAPI dependency injection
    embeddings.py        # Embedding model loader (singleton)
    document_processor.py  # File parsing, text chunking
    vector_store.py      # Facade: routes to chroma or pgvector
    chroma_vector_store.py
    pg_vector_store.py
    scheduler.py         # APScheduler setup + sync jobs
    connectors/
      __init__.py        # Re-exports all connectors
      *_connector.py     # Individual connector implementations
```

---

## Adding a New Connector

Follow this five-step process to add a new external data source connector.

### Step 1: Create the connector file

```python
# src/core/connectors/myservice_connector.py
from __future__ import annotations
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from ..document_processor import ParsedDocument, _make_id


@dataclass
class MyServiceConfig:
    host: str
    api_key: str
    # Add all config fields here
    row_limit: int = 1000


class MyServiceConnector:
    def __init__(self, config: MyServiceConfig):
        self.config = config

    def _test_sync(self) -> dict:
        try:
            # Try to connect and run a lightweight check
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _collect(self) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        # Fetch data, build ParsedDocument instances
        # ...
        return docs, {"last_ts": time.time()}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        # Implement incremental logic, or fall back to full sync:
        return await self.sync_documents()
```

**`ParsedDocument` fields:**

| Field | Type | Description |
|---|---|---|
| `doc_id` | str | Stable unique ID — use `_make_id(key_string)` |
| `title` | str | Human-readable title |
| `source` | str | Source URI, e.g. `myservice://host/path` |
| `content` | str | Full text content |
| `metadata` | dict | Must include `source_type` key |

### Step 2: Add to `DataSourceType` enum

In `src/core/models.py`:

```python
class DataSourceType(str, enum.Enum):
    # ... existing types ...
    myservice = "myservice"
```

### Step 3: Export from `__init__.py`

In `src/core/connectors/__init__.py`:

```python
from .myservice_connector import MyServiceConnector, MyServiceConfig
```

### Step 4: Add to `_make_connector()` in `datasources.py`

In `src/api/routes/datasources.py`:

```python
elif ds.type == DataSourceType.myservice:
    from src.core.connectors.myservice_connector import MyServiceConnector, MyServiceConfig
    return MyServiceConnector(MyServiceConfig(
        host=cfg.get("host", ""),
        api_key=cfg.get("api_key", ""),
        row_limit=cfg.get("row_limit", 1000),
    ))
```

Also add sensitive fields to `_SENSITIVE` if the connector uses secrets:

```python
_SENSITIVE = {..., "api_key"}
```

### Step 5: Add to the BM25 set (SQL sources only)

If the connector produces structured tabular data where BM25 re-scoring is beneficial, add the type to the BM25 SQL types set in `src/api/routes/me.py`:

```python
DataSource.type.in_([
    ...,
    DataSourceType.myservice,
])
```

---

## Writing Tests

### Unit test for a connector

```python
# tests/test_myservice_datasource.py
import pytest
from unittest.mock import patch, MagicMock

def test_myservice_collect():
    # If myservice library is not installed, patch sys.modules
    mock_lib = MagicMock()
    with patch.dict("sys.modules", {"myservice_lib": mock_lib}):
        from src.core.connectors.myservice_connector import (
            MyServiceConnector, MyServiceConfig
        )
        cfg = MyServiceConfig(host="localhost", api_key="test-key")
        conn = MyServiceConnector(cfg)

        mock_lib.Client.return_value.__enter__.return_value.fetch.return_value = [
            {"id": 1, "title": "Hello", "body": "World"}
        ]

        docs, state = conn._collect()
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "myservice"
```

### Testing the API layer

```python
import pytest

def test_create_myservice_datasource(authed_client):
    resp = authed_client.post("/me/datasources", json={
        "name": "My Service",
        "type": "myservice",
        "collection": "myservice-data",
        "sync_interval_minutes": 60,
        "config": {
            "host": "localhost",
            "api_key": "s3cr3t",
        }
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["config"]["api_key"] == "***"  # must be masked
```

---

## Code Style

- Python 3.11+ syntax
- Type annotations on all public function signatures
- Async connectors always delegate blocking I/O to `ThreadPoolExecutor` via `run_in_executor`
- No module-level side effects in connector files — imports happen inside methods when the optional dependency may not be installed
- Field names in `_SENSITIVE` must match exactly the keys used in the config dict

---

## Making a Release

```bash
# Bump version in pyproject.toml
# Commit and tag
git tag v1.2.3
git push origin v1.2.3

# Build and publish
python -m build
twine upload dist/*
```
