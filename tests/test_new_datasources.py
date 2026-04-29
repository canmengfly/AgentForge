"""Tests for the six new data source connectors: S3, Doris, Elasticsearch, MongoDB, ClickHouse, Hive."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# S3 Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3Connector:

    def _make_connector(self, **kw):
        from src.core.connectors.s3_connector import S3Config, S3Connector
        cfg = S3Config(
            bucket="test-bucket",
            access_key_id="AKI",
            secret_access_key="SECRET",
            region="us-east-1",
            **kw,
        )
        return S3Connector(cfg)

    def _mock_s3_client(self, keys: list[str] | None = None):
        """Build a mock boto3 S3 client with the given object keys."""
        client = MagicMock()
        client.head_bucket.return_value = {}

        keys = keys or []
        import time

        contents = []
        for key in keys:
            obj = MagicMock()
            obj.__getitem__ = lambda self, k, _k=key: (
                _k if k == "Key"
                else MagicMock(timestamp=lambda: time.time() + 1)
            )
            contents.append({"Key": key, "LastModified": MagicMock(timestamp=lambda: time.time() + 1)})

        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": contents}]
        client.get_paginator.return_value = paginator
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b"Hello S3 content")}
        return client

    def test_test_connection_ok(self):
        conn = self._make_connector()
        client = MagicMock()
        client.head_bucket.return_value = {}
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is True

    def test_test_connection_failure(self):
        conn = self._make_connector()
        client = MagicMock()
        client.head_bucket.side_effect = Exception("NoSuchBucket")
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is False
        assert "NoSuchBucket" in result["error"]

    def test_sync_documents_empty_bucket(self):
        conn = self._make_connector()
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        client.get_paginator.return_value = paginator
        with patch.object(conn, "_make_client", return_value=client):
            docs, cursor = run(conn.sync_documents())
        assert docs == []
        assert "last_mtime" in cursor

    def test_sync_filters_unsupported_extensions(self):
        conn = self._make_connector()
        import time
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": [
            {"Key": "file.exe", "LastModified": MagicMock(timestamp=lambda: time.time() + 1)},
            {"Key": "readme.txt", "LastModified": MagicMock(timestamp=lambda: time.time() + 1)},
        ]}]
        client.get_paginator.return_value = paginator
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b"text content")}
        with patch.object(conn, "_make_client", return_value=client):
            docs, _ = run(conn.sync_documents())
        assert all(d.source.endswith(".txt") or "readme" in d.source for d in docs)
        filenames = [d.source.split("/")[-1] for d in docs]
        assert "file.exe" not in filenames

    def test_sync_sets_source_type_metadata(self):
        conn = self._make_connector()
        import time
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": [
            {"Key": "docs/guide.txt", "LastModified": MagicMock(timestamp=lambda: time.time() + 1)},
        ]}]
        client.get_paginator.return_value = paginator
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b"guide content")}
        with patch.object(conn, "_make_client", return_value=client):
            docs, _ = run(conn.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "s3"
        assert docs[0].metadata["s3_bucket"] == "test-bucket"

    def test_sync_incremental_uses_cursor(self):
        conn = self._make_connector()
        import time
        old_time = time.time() - 3600
        client = MagicMock()
        paginator = MagicMock()
        # Object mtime is "now" > cursor
        paginator.paginate.return_value = [{"Contents": [
            {"Key": "new.txt", "LastModified": MagicMock(timestamp=lambda: time.time() + 1)},
        ]}]
        client.get_paginator.return_value = paginator
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b"new content")}
        with patch.object(conn, "_make_client", return_value=client):
            docs, cursor = run(conn.sync_incremental({"last_mtime": old_time}))
        assert len(docs) == 1

    def test_endpoint_url_passed_to_boto3(self):
        conn = self._make_connector(endpoint_url="http://minio:9000")
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock(head_bucket=MagicMock(return_value={}))
            try:
                conn._make_client()
            except Exception:
                pass
        call_kwargs = mock_boto.call_args[1]
        assert call_kwargs.get("endpoint_url") == "http://minio:9000"

    def test_boto3_import_error(self):
        conn = self._make_connector()
        with patch.dict("sys.modules", {"boto3": None}):
            with pytest.raises(RuntimeError, match="boto3"):
                conn._make_client()


# ═══════════════════════════════════════════════════════════════════════════════
# Doris Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestDorisConnector:

    def _make_connector(self, **kw):
        from src.core.connectors.doris_connector import DorisConfig, DorisConnector
        cfg = DorisConfig(host="doris-host", database="test_db", username="admin", password="pass", **kw)
        return DorisConnector(cfg)

    def test_delegates_to_sql_connector(self):
        conn = self._make_connector()
        assert hasattr(conn, "_inner")

    def test_default_port_9030(self):
        conn = self._make_connector()
        assert conn._inner.config.port == 9030

    def test_source_type_overridden_to_doris(self):
        conn = self._make_connector()
        mock_docs = [MagicMock(metadata={"source_type": "sql"})]
        mock_cursor = {"last_mtime": 0.0}

        async def _fake():
            return mock_docs, mock_cursor

        with patch.object(conn._inner, "sync_documents", side_effect=_fake):
            docs, _ = run(conn.sync_documents())
        for doc in docs:
            assert doc.metadata["source_type"] == "doris"

    def test_incremental_source_type(self):
        conn = self._make_connector()
        mock_docs = [MagicMock(metadata={"source_type": "sql"})]
        mock_cursor = {"last_mtime": 0.0}
        async def _fake(cursor):
            return mock_docs, mock_cursor
        with patch.object(conn._inner, "sync_incremental", side_effect=_fake):
            docs, _ = run(conn.sync_incremental({}))
        for doc in docs:
            assert doc.metadata["source_type"] == "doris"

    def test_test_connection_delegates(self):
        conn = self._make_connector()
        async def _ok():
            return {"ok": True}
        with patch.object(conn._inner, "test_connection", side_effect=_ok):
            result = run(conn.test_connection())
        assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Elasticsearch Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestElasticsearchConnector:

    def _make_connector(self, **kw):
        from src.core.connectors.elasticsearch_connector import ElasticsearchConfig, ElasticsearchConnector
        cfg = ElasticsearchConfig(hosts=["http://localhost:9200"], index="test-index", **kw)
        return ElasticsearchConnector(cfg)

    def _mock_es_client(self, hits=None):
        client = MagicMock()
        client.indices.exists.return_value = True
        hits = hits or []
        client.search.return_value = {
            "_scroll_id": "scroll123",
            "hits": {"hits": hits},
        }
        client.scroll.return_value = {"hits": {"hits": []}}
        client.clear_scroll.return_value = {}
        return client

    def test_test_connection_ok(self):
        conn = self._make_connector()
        client = self._mock_es_client()
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is True

    def test_test_connection_index_missing(self):
        conn = self._make_connector()
        client = self._mock_es_client()
        client.indices.exists.return_value = False
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is False
        assert "test-index" in result["error"]

    def test_sync_documents_empty(self):
        conn = self._make_connector()
        client = self._mock_es_client(hits=[])
        with patch.object(conn, "_make_client", return_value=client):
            docs, cursor = run(conn.sync_documents())
        assert docs == []
        assert "last_ts" in cursor

    def test_sync_documents_creates_docs(self):
        conn = self._make_connector(text_fields=["title", "body"])
        hits = [
            {"_id": "1", "_source": {"title": "Hello", "body": "World"}},
            {"_id": "2", "_source": {"title": "Foo",   "body": "Bar"}},
        ]
        client = self._mock_es_client(hits=hits)
        with patch.object(conn, "_make_client", return_value=client):
            docs, _ = run(conn.sync_documents())
        assert len(docs) == 2
        assert docs[0].metadata["source_type"] == "elasticsearch"
        assert docs[0].metadata["es_index"] == "test-index"

    def test_text_fields_concat(self):
        conn = self._make_connector(text_fields=["title", "body"])
        hit = {"_id": "1", "_source": {"title": "T", "body": "B", "noise": "N"}}
        doc = conn._hit_to_doc(hit)
        assert "T" in doc.content
        assert "B" in doc.content
        assert "noise" not in doc.content

    def test_all_fields_when_text_fields_empty(self):
        conn = self._make_connector()
        hit = {"_id": "1", "_source": {"title": "T", "body": "B"}}
        doc = conn._hit_to_doc(hit)
        assert doc is not None
        assert "T" in doc.content
        assert "B" in doc.content

    def test_sync_incremental_passes_cursor(self):
        conn = self._make_connector(timestamp_field="created_at")
        client = self._mock_es_client()
        with patch.object(conn, "_make_client", return_value=client):
            run(conn.sync_incremental({"last_ts": 1_000_000.0}))
        call_body = client.search.call_args[1]["body"]
        assert "range" in call_body["query"]

    def test_import_error(self):
        conn = self._make_connector()
        with patch.dict("sys.modules", {"elasticsearch": None}):
            with pytest.raises(RuntimeError, match="elasticsearch"):
                conn._make_client()

    def test_api_key_passed_to_client(self):
        conn = self._make_connector(api_key="mykey")
        mock_es_cls = MagicMock(return_value=MagicMock())
        mock_es_module = MagicMock(Elasticsearch=mock_es_cls)
        with patch.dict("sys.modules", {"elasticsearch": mock_es_module}):
            conn._make_client()
        call_kwargs = mock_es_cls.call_args[1]
        assert call_kwargs.get("api_key") == "mykey"

    def test_basic_auth_used_without_api_key(self):
        conn = self._make_connector(username="elastic", password="secret")
        mock_es_cls = MagicMock(return_value=MagicMock())
        mock_es_module = MagicMock(Elasticsearch=mock_es_cls)
        with patch.dict("sys.modules", {"elasticsearch": mock_es_module}):
            conn._make_client()
        call_kwargs = mock_es_cls.call_args[1]
        assert call_kwargs.get("http_auth") == ("elastic", "secret")
        assert "api_key" not in call_kwargs


# ═══════════════════════════════════════════════════════════════════════════════
# MongoDB Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestMongoDBConnector:

    def _make_connector(self, **kw):
        from src.core.connectors.mongodb_connector import MongoDBConfig, MongoDBConnector
        cfg = MongoDBConfig(uri="mongodb://localhost:27017", database="test_db", **kw)
        return MongoDBConnector(cfg)

    def _mock_mongo_client(self, col_names=None, records=None):
        client = MagicMock()
        db = MagicMock()
        client.__getitem__ = lambda self, name: db
        col_names = col_names or ["col1"]
        records = records or [{"_id": "1", "title": "Test", "body": "Content"}]
        db.list_collection_names.return_value = col_names
        col = MagicMock()
        col.find.return_value = iter(records)
        db.__getitem__ = lambda self, name: col
        return client

    def test_test_connection_ok(self):
        conn = self._make_connector()
        client = self._mock_mongo_client()
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is True

    def test_test_connection_failure(self):
        conn = self._make_connector()
        client = MagicMock()
        db = MagicMock()
        client.__getitem__ = lambda self, name: db
        db.list_collection_names.side_effect = Exception("auth failed")
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is False

    def test_sync_returns_documents(self):
        conn = self._make_connector()
        client = self._mock_mongo_client(
            col_names=["articles"],
            records=[{"_id": "1", "title": "Hello", "body": "World"}],
        )
        with patch.object(conn, "_make_client", return_value=client):
            docs, cursor = run(conn.sync_documents())
        assert len(docs) >= 1
        assert docs[0].metadata["source_type"] == "mongodb"

    def test_source_type_metadata(self):
        conn = self._make_connector()
        record = {"_id": "x1", "name": "item", "value": "42"}
        doc = conn._record_to_doc(record, "products")
        assert doc is not None
        assert doc.metadata["source_type"] == "mongodb"
        assert doc.metadata["mongo_db"] == "test_db"
        assert doc.metadata["mongo_collection"] == "products"

    def test_text_fields_filter(self):
        conn = self._make_connector(text_fields=["title"])
        record = {"_id": "1", "title": "Hello", "noise": "ignored"}
        doc = conn._record_to_doc(record, "col")
        assert "Hello" in doc.content
        assert "ignored" not in doc.content

    def test_specific_collections_respected(self):
        conn = self._make_connector(collections=["orders"])
        client = MagicMock()
        db = MagicMock()
        client.__getitem__ = lambda self, name: db
        col = MagicMock()
        col.find.return_value = iter([{"_id": "1", "item": "book"}])
        db.__getitem__ = lambda self, name: col
        with patch.object(conn, "_make_client", return_value=client):
            docs, _ = run(conn.sync_documents())
        db.list_collection_names.assert_not_called()

    def test_empty_record_skipped(self):
        conn = self._make_connector()
        doc = conn._record_to_doc({"_id": "1"}, "col")
        assert doc is None

    def test_pymongo_import_error(self):
        conn = self._make_connector()
        with patch.dict("sys.modules", {"pymongo": None}):
            with pytest.raises(RuntimeError, match="pymongo"):
                conn._make_client()


# ═══════════════════════════════════════════════════════════════════════════════
# ClickHouse Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestClickHouseConnector:

    def _make_connector(self, **kw):
        from src.core.connectors.clickhouse_connector import ClickHouseConfig, ClickHouseConnector
        cfg = ClickHouseConfig(host="localhost", database="default", **kw)
        return ClickHouseConnector(cfg)

    def _mock_ch_client(self, table_rows=None):
        client = MagicMock()
        client.query.side_effect = lambda sql, **kw: self._make_result(sql, table_rows)
        return client

    def _make_result(self, sql, table_rows):
        result = MagicMock()
        if "system.tables" in sql:
            result.result_rows = [("events",), ("logs",)]
            return result
        result.column_names = ["id", "msg"]
        result.result_rows = table_rows or [("1", "hello")]
        return result

    def test_test_connection_ok(self):
        conn = self._make_connector()
        client = MagicMock()
        client.query.return_value = MagicMock()
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is True

    def test_test_connection_failure(self):
        conn = self._make_connector()
        client = MagicMock()
        client.query.side_effect = Exception("connection refused")
        with patch.object(conn, "_make_client", return_value=client):
            result = run(conn.test_connection())
        assert result["ok"] is False

    def test_sync_creates_documents(self):
        conn = self._make_connector(tables=["events"])
        client = MagicMock()
        result = MagicMock()
        result.column_names = ["id", "message"]
        result.result_rows = [("1", "click event"), ("2", "page view")]
        client.query.return_value = result
        with patch.object(conn, "_make_client", return_value=client):
            docs, cursor = run(conn.sync_documents())
        assert len(docs) == 2
        assert docs[0].metadata["source_type"] == "clickhouse"

    def test_row_to_doc_sets_metadata(self):
        conn = self._make_connector()
        record = {"id": "42", "event": "click"}
        doc = conn._row_to_doc(record, "events")
        assert doc is not None
        assert doc.metadata["ch_database"] == "default"
        assert doc.metadata["ch_table"] == "events"
        assert doc.metadata["source_type"] == "clickhouse"

    def test_empty_row_skipped(self):
        conn = self._make_connector()
        doc = conn._row_to_doc({}, "events")
        assert doc is None

    def test_incremental_falls_back_to_full_sync(self):
        conn = self._make_connector()
        async def _full():
            return [], {"last_ts": 0}
        with patch.object(conn, "sync_documents", side_effect=_full):
            docs, cursor = run(conn.sync_incremental({"last_ts": 1000}))
        assert docs == []

    def test_clickhouse_import_error(self):
        conn = self._make_connector()
        with patch.dict("sys.modules", {"clickhouse_connect": None}):
            with pytest.raises(RuntimeError, match="clickhouse-connect"):
                conn._make_client()


# ═══════════════════════════════════════════════════════════════════════════════
# Hive Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestHiveConnector:

    def _make_connector(self, **kw):
        from src.core.connectors.hive_connector import HiveConfig, HiveConnector
        cfg = HiveConfig(host="hive-server", database="analytics", **kw)
        return HiveConnector(cfg)

    def _mock_hive_connection(self, table_names=None, rows=None):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        table_names = table_names or ["fact_sales"]
        rows = rows or [(1, "item_a"), (2, "item_b")]
        cursor.fetchall.side_effect = [
            [(t,) for t in table_names],  # SHOW TABLES
            rows,                          # SELECT *
        ]
        cursor.description = [("id", None), ("name", None)]
        return conn

    def test_test_connection_ok(self):
        conn = self._make_connector()
        hive_conn = self._mock_hive_connection()
        with patch.object(conn, "_make_connection", return_value=hive_conn):
            result = run(conn.test_connection())
        assert result["ok"] is True

    def test_test_connection_failure(self):
        conn = self._make_connector()
        with patch.object(conn, "_make_connection", side_effect=Exception("transport error")):
            result = run(conn.test_connection())
        assert result["ok"] is False
        assert "transport error" in result["error"]

    def test_sync_creates_documents(self):
        conn = self._make_connector()
        hive_conn = self._mock_hive_connection(
            table_names=["fact_orders"],
            rows=[(1, "order_a"), (2, "order_b")],
        )
        with patch.object(conn, "_make_connection", return_value=hive_conn):
            docs, cursor = run(conn.sync_documents())
        assert len(docs) == 2
        assert docs[0].metadata["source_type"] == "hive"

    def test_row_to_doc_sets_metadata(self):
        conn = self._make_connector()
        record = {"id": 1, "product": "laptop"}
        doc = conn._row_to_doc(record, "products")
        assert doc is not None
        assert doc.metadata["hive_database"] == "analytics"
        assert doc.metadata["hive_table"] == "products"
        assert doc.metadata["source_type"] == "hive"

    def test_specific_tables_respected(self):
        conn = self._make_connector(tables=["dim_product"])
        hive_conn = MagicMock()
        cursor = MagicMock()
        hive_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [(1, "tv")]
        cursor.description = [("id", None), ("name", None)]
        with patch.object(conn, "_make_connection", return_value=hive_conn):
            docs, _ = run(conn.sync_documents())
        # SHOW TABLES should NOT be called when tables are specified
        show_calls = [c for c in cursor.execute.call_args_list if "SHOW" in str(c)]
        assert len(show_calls) == 0

    def test_incremental_falls_back_to_full_sync(self):
        conn = self._make_connector()
        async def _full():
            return [], {"last_ts": 0}
        with patch.object(conn, "sync_documents", side_effect=_full):
            docs, _ = run(conn.sync_incremental({"last_ts": 9999}))
        assert docs == []

    def test_pyhive_import_error(self):
        conn = self._make_connector()
        with patch.dict("sys.modules", {"pyhive": None, "pyhive.hive": None}):
            with pytest.raises(RuntimeError, match="pyhive"):
                conn._make_connection()

    def test_ldap_auth_passes_password(self):
        conn = self._make_connector(auth="LDAP", username="alice", password="s3cret")
        mock_connect = MagicMock(return_value=MagicMock())
        mock_hive_module = MagicMock(connect=mock_connect)
        mock_pyhive = MagicMock(hive=mock_hive_module)
        with patch.dict("sys.modules", {"pyhive": mock_pyhive, "pyhive.hive": mock_hive_module}):
            conn._make_connection()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs.get("password") == "s3cret"

    def test_nosasl_auth_no_password(self):
        conn = self._make_connector(auth="NOSASL", username="alice", password="s3cret")
        mock_connect = MagicMock(return_value=MagicMock())
        mock_hive_module = MagicMock(connect=mock_connect)
        mock_pyhive = MagicMock(hive=mock_hive_module)
        with patch.dict("sys.modules", {"pyhive": mock_pyhive, "pyhive.hive": mock_hive_module}):
            conn._make_connection()
        call_kwargs = mock_connect.call_args[1]
        assert "password" not in call_kwargs


# ═══════════════════════════════════════════════════════════════════════════════
# DataSourceType enum
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataSourceTypeEnum:
    def test_all_new_types_present(self):
        from src.core.models import DataSourceType
        for t in ("s3", "doris", "elasticsearch", "mongodb", "clickhouse", "hive"):
            assert hasattr(DataSourceType, t), f"DataSourceType missing: {t}"

    def test_existing_types_still_present(self):
        from src.core.models import DataSourceType
        for t in ("oss", "mysql", "postgres", "feishu", "dingtalk", "tencent_docs"):
            assert hasattr(DataSourceType, t), f"DataSourceType regression: {t}"


# ═══════════════════════════════════════════════════════════════════════════════
# _parse_config helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseConfig:
    def _parse(self, raw):
        from src.api.routes.datasources import _parse_config
        return _parse_config(raw)

    def test_hosts_string_split(self):
        cfg = self._parse({"hosts": "http://a:9200, http://b:9200"})
        assert cfg["hosts"] == ["http://a:9200", "http://b:9200"]

    def test_collections_string_split(self):
        cfg = self._parse({"collections": "users, orders"})
        assert cfg["collections"] == ["users", "orders"]

    def test_size_int_cast(self):
        cfg = self._parse({"size": "200"})
        assert cfg["size"] == 200

    def test_secure_bool_cast(self):
        cfg = self._parse({"secure": "true"})
        assert cfg["secure"] is True
        cfg2 = self._parse({"secure": "false"})
        assert cfg2["secure"] is False

    def test_verify_certs_bool_cast(self):
        cfg = self._parse({"verify_certs": "yes"})
        assert cfg["verify_certs"] is True

    def test_text_fields_string_split(self):
        cfg = self._parse({"text_fields": "title, body, description"})
        assert cfg["text_fields"] == ["title", "body", "description"]


# ═══════════════════════════════════════════════════════════════════════════════
# API — datasource CRUD for new types
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewDatasourceAPI:

    def test_create_s3_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "My S3",
            "type": "s3",
            "config": {
                "bucket": "test-bucket",
                "access_key_id": "AKI",
                "secret_access_key": "SECRET",
                "region": "us-east-1",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "s3"
        assert data["config"]["secret_access_key"] == "***"  # masked

    def test_create_elasticsearch_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "My ES",
            "type": "elasticsearch",
            "config": {
                "hosts": "http://localhost:9200",
                "index": "my-index",
                "api_key": "super-secret",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "elasticsearch"
        assert data["config"]["api_key"] == "***"

    def test_create_mongodb_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "My MongoDB",
            "type": "mongodb",
            "config": {
                "uri": "mongodb://localhost:27017",
                "database": "test_db",
                "collections": "users, orders",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "mongodb"

    def test_create_doris_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "Doris",
            "type": "doris",
            "config": {
                "host": "doris-fe",
                "database": "sales",
                "username": "admin",
                "password": "pass",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "doris"

    def test_create_clickhouse_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "ClickHouse",
            "type": "clickhouse",
            "config": {
                "host": "ch-server",
                "database": "events",
                "username": "default",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "clickhouse"

    def test_create_hive_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "Hive",
            "type": "hive",
            "config": {
                "host": "hive-server",
                "database": "analytics",
                "auth": "NOSASL",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "hive"

    def test_new_datasources_appear_in_list(self, as_user):
        for ds_type in ("s3", "elasticsearch", "mongodb"):
            as_user.post("/api/datasources", json={
                "name": f"DS {ds_type}",
                "type": ds_type,
                "config": {"bucket": "b", "access_key_id": "k", "secret_access_key": "s",
                           "hosts": "http://localhost:9200", "index": "i",
                           "uri": "mongodb://localhost", "database": "db"}.get(
                    ds_type, {"hosts": "http://localhost:9200", "index": "i"}
                ) if ds_type in ("elasticsearch",) else (
                    {"bucket": "b", "access_key_id": "k", "secret_access_key": "s"} if ds_type == "s3"
                    else {"uri": "mongodb://localhost", "database": "db"}
                ),
            })
        resp = as_user.get("/api/datasources")
        types = {ds["type"] for ds in resp.json()}
        assert "s3" in types or "elasticsearch" in types or "mongodb" in types

    def test_sensitive_fields_masked_in_response(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "S3 mask test",
            "type": "s3",
            "config": {"bucket": "b", "access_key_id": "AKI", "secret_access_key": "TOPSECRET"},
        })
        assert resp.json()["config"]["secret_access_key"] == "***"

    def test_delete_new_datasource(self, as_user):
        resp = as_user.post("/api/datasources", json={
            "name": "to_delete",
            "type": "mongodb",
            "config": {"uri": "mongodb://localhost", "database": "db"},
        })
        ds_id = resp.json()["id"]
        del_resp = as_user.delete(f"/api/datasources/{ds_id}")
        assert del_resp.json()["deleted"] is True
