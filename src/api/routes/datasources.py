"""Data source management API — OSS buckets and SQL databases."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.core.deps import CurrentUser, DBSession
from src.core.models import DataSource, DataSourceStatus, DataSourceType

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

_SENSITIVE = {
    "access_key_secret", "password", "app_secret", "client_secret",
    "access_token", "refresh_token", "secret_access_key", "api_key",
    "api_token", "token", "secret_key", "credentials_json",
}


def _mask(config: dict) -> dict:
    return {k: "***" if k in _SENSITIVE and v else v for k, v in config.items()}


def _parse_config(raw: dict) -> dict:
    cfg = dict(raw)
    # Normalise singular "table" → "tables" list
    if "table" in cfg and "tables" not in cfg:
        t = cfg.pop("table")
        cfg["tables"] = [t.strip()] if t and t.strip() else []
    for list_field in ("tables", "collections", "hosts", "text_fields", "file_types"):
        if list_field in cfg and isinstance(cfg[list_field], str):
            cfg[list_field] = [v.strip() for v in cfg[list_field].split(",") if v.strip()]
    for int_field in ("port", "row_limit", "size"):
        if int_field in cfg and cfg[int_field] != "":
            try:
                cfg[int_field] = int(cfg[int_field])
            except (TypeError, ValueError):
                pass
    for bool_field in ("secure", "verify_certs"):
        if bool_field in cfg and isinstance(cfg[bool_field], str):
            cfg[bool_field] = cfg[bool_field].lower() in ("true", "1", "yes")
    return cfg


def _make_connector(ds: DataSource):
    cfg = json.loads(ds.config_json)
    cfg = _parse_config(cfg)

    if ds.type == DataSourceType.oss:
        from src.core.connectors.oss_connector import OSSConfig, OSSConnector
        return OSSConnector(OSSConfig(**cfg))
    if ds.type == DataSourceType.s3:
        from src.core.connectors.s3_connector import S3Config, S3Connector
        return S3Connector(S3Config(**cfg))
    if ds.type in (DataSourceType.mysql, DataSourceType.postgres):
        from src.core.connectors.sql_connector import SQLConfig, SQLConnector
        cfg["driver"] = "mysql" if ds.type == DataSourceType.mysql else "postgres"
        return SQLConnector(SQLConfig(**cfg))
    if ds.type == DataSourceType.doris:
        from src.core.connectors.doris_connector import DorisConfig, DorisConnector
        return DorisConnector(DorisConfig(**cfg))
    if ds.type == DataSourceType.clickhouse:
        from src.core.connectors.clickhouse_connector import ClickHouseConfig, ClickHouseConnector
        return ClickHouseConnector(ClickHouseConfig(**cfg))
    if ds.type == DataSourceType.hive:
        from src.core.connectors.hive_connector import HiveConfig, HiveConnector
        return HiveConnector(HiveConfig(**cfg))
    if ds.type == DataSourceType.elasticsearch:
        from src.core.connectors.elasticsearch_connector import ElasticsearchConfig, ElasticsearchConnector
        return ElasticsearchConnector(ElasticsearchConfig(**cfg))
    if ds.type == DataSourceType.mongodb:
        from src.core.connectors.mongodb_connector import MongoDBConfig, MongoDBConnector
        return MongoDBConnector(MongoDBConfig(**cfg))
    if ds.type == DataSourceType.tencent_cos:
        from src.core.connectors.tencent_cos_connector import TencentCOSConfig, TencentCOSConnector
        return TencentCOSConnector(TencentCOSConfig(**cfg))
    if ds.type == DataSourceType.huawei_obs:
        from src.core.connectors.huawei_obs_connector import HuaweiOBSConfig, HuaweiOBSConnector
        return HuaweiOBSConnector(HuaweiOBSConfig(**cfg))
    if ds.type == DataSourceType.oracle:
        from src.core.connectors.oracle_connector import OracleConfig, OracleConnector
        return OracleConnector(OracleConfig(**cfg))
    if ds.type == DataSourceType.sqlserver:
        from src.core.connectors.sqlserver_connector import SQLServerConfig, SQLServerConnector
        return SQLServerConnector(SQLServerConfig(**cfg))
    if ds.type == DataSourceType.tidb:
        from src.core.connectors.tidb_connector import TiDBConfig, TiDBConnector
        return TiDBConnector(TiDBConfig(**cfg))
    if ds.type == DataSourceType.oceanbase:
        from src.core.connectors.oceanbase_connector import OceanBaseConfig, OceanBaseConnector
        return OceanBaseConnector(OceanBaseConfig(**cfg))
    if ds.type == DataSourceType.snowflake:
        from src.core.connectors.snowflake_connector import SnowflakeConfig, SnowflakeConnector
        return SnowflakeConnector(SnowflakeConfig(**cfg))
    if ds.type == DataSourceType.feishu:
        from src.core.connectors.feishu_connector import FeishuConfig, FeishuConnector
        return FeishuConnector(FeishuConfig(**cfg))
    if ds.type == DataSourceType.dingtalk:
        from src.core.connectors.dingtalk_connector import DingTalkConfig, DingTalkConnector
        return DingTalkConnector(DingTalkConfig(**cfg))
    if ds.type == DataSourceType.tencent_docs:
        from src.core.connectors.tencent_docs_connector import TencentDocsConfig, TencentDocsConnector
        return TencentDocsConnector(TencentDocsConfig(**cfg))
    if ds.type == DataSourceType.confluence:
        from src.core.connectors.confluence_connector import ConfluenceConfig, ConfluenceConnector
        is_cloud = cfg.pop("is_cloud", True)
        if isinstance(is_cloud, str):
            is_cloud = is_cloud.lower() not in ("false", "0", "no")
        return ConfluenceConnector(ConfluenceConfig(is_cloud=is_cloud, **cfg))
    if ds.type == DataSourceType.notion:
        from src.core.connectors.notion_connector import NotionConfig, NotionConnector
        return NotionConnector(NotionConfig(**cfg))
    if ds.type == DataSourceType.yuque:
        from src.core.connectors.yuque_connector import YuqueConfig, YuqueConnector
        return YuqueConnector(YuqueConfig(**cfg))
    if ds.type == DataSourceType.github:
        from src.core.connectors.github_connector import GitHubConfig, GitHubConnector
        return GitHubConnector(GitHubConfig(**cfg))
    if ds.type == DataSourceType.gitlab:
        from src.core.connectors.gitlab_connector import GitLabConfig, GitLabConnector
        return GitLabConnector(GitLabConfig(**cfg))
    if ds.type == DataSourceType.sharepoint:
        from src.core.connectors.sharepoint_connector import SharePointConfig, SharePointConnector
        return SharePointConnector(SharePointConfig(**cfg))
    if ds.type == DataSourceType.google_drive:
        from src.core.connectors.google_drive_connector import GoogleDriveConfig, GoogleDriveConnector
        return GoogleDriveConnector(GoogleDriveConfig(**cfg))
    raise ValueError(f"Unknown type: {ds.type}")


def _actual_col(ds: DataSource) -> str:
    """ChromaDB collection name in the owning user's namespace."""
    return f"u{ds.created_by}_{ds.collection}"


def _to_response(ds: DataSource) -> dict:
    from src.core.scheduler import next_run_at
    cfg = _mask(json.loads(ds.config_json))
    return {**ds.to_dict(), "config": cfg, "next_run_at": next_run_at(ds.id)}


def _get_owned(ds_id: int, user_id: int, db) -> DataSource:
    ds = db.get(DataSource, ds_id)
    if not ds or ds.created_by != user_id:
        raise HTTPException(404, "Data source not found")
    return ds


# ── Request models ───────────────────────────────────────────────────────────

class CreateDataSourceRequest(BaseModel):
    name: str
    type: DataSourceType
    config: dict[str, Any]
    collection: str = ""
    sync_interval: int | None = Field(default=None, ge=1)  # minutes


class UpdateScheduleRequest(BaseModel):
    sync_interval: int | None = Field(default=None, ge=1)  # None = disable


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_datasources(user: CurrentUser, db: DBSession):
    sources = db.query(DataSource).filter(DataSource.created_by == user.id).all()
    return [_to_response(s) for s in sources]


@router.post("")
async def create_datasource(body: CreateDataSourceRequest, user: CurrentUser, db: DBSession):
    cfg = _parse_config(body.config)
    slug = body.name.lower()
    for ch in " -./":
        slug = slug.replace(ch, "_")
    collection = body.collection.strip() or f"ds_{slug}"

    ds = DataSource(
        name=body.name,
        type=body.type,
        config_json=json.dumps(cfg),
        collection=collection,
        created_by=user.id,
        sync_interval=body.sync_interval,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)

    if body.sync_interval:
        from src.core.scheduler import schedule_ds
        schedule_ds(ds.id, body.sync_interval)

    return _to_response(ds)


@router.delete("/{ds_id}")
async def delete_datasource(ds_id: int, user: CurrentUser, db: DBSession):
    ds = _get_owned(ds_id, user.id, db)
    from src.core.vector_store import delete_collection
    from src.core.scheduler import unschedule_ds
    unschedule_ds(ds_id)
    try:
        delete_collection(_actual_col(ds))
    except Exception:
        pass
    db.delete(ds)
    db.commit()
    return {"deleted": True}


@router.post("/{ds_id}/test")
async def test_datasource(ds_id: int, user: CurrentUser, db: DBSession):
    ds = _get_owned(ds_id, user.id, db)
    connector = _make_connector(ds)
    return await connector.test_connection()


@router.post("/{ds_id}/sync")
async def sync_datasource(
    ds_id: int,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: DBSession,
):
    ds = _get_owned(ds_id, user.id, db)
    if ds.status == DataSourceStatus.syncing:
        raise HTTPException(409, "Sync already in progress")
    ds.status = DataSourceStatus.syncing
    ds.last_error = None
    db.commit()
    background_tasks.add_task(_run_sync, ds_id)
    return {"status": "syncing"}


@router.patch("/{ds_id}/schedule")
async def update_schedule(ds_id: int, body: UpdateScheduleRequest, user: CurrentUser, db: DBSession):
    """Enable or disable periodic incremental sync for a datasource."""
    ds = _get_owned(ds_id, user.id, db)
    ds.sync_interval = body.sync_interval
    db.commit()

    from src.core.scheduler import schedule_ds, unschedule_ds
    if body.sync_interval:
        schedule_ds(ds.id, body.sync_interval)
    else:
        unschedule_ds(ds.id)

    return _to_response(ds)


@router.get("/{ds_id}/status")
async def get_status(ds_id: int, user: CurrentUser, db: DBSession):
    ds = _get_owned(ds_id, user.id, db)
    return _to_response(ds)


# ── Background tasks ─────────────────────────────────────────────────────────

async def _run_sync(ds_id: int) -> None:
    """Full sync: rebuild collection from scratch, then update cursor."""
    from src.core.database import SessionLocal
    from src.core.vector_store import add_document, delete_collection

    db = SessionLocal()
    try:
        ds = db.get(DataSource, ds_id)
        if not ds:
            return

        connector = _make_connector(ds)
        actual_col = _actual_col(ds)

        try:
            delete_collection(actual_col)
        except Exception:
            pass

        docs, cursor = await connector.sync_documents()

        indexed = 0
        failed = 0
        for doc in docs:
            try:
                add_document(doc, actual_col)
                indexed += 1
            except Exception as doc_exc:
                failed += 1
                if not ds.last_error:
                    ds.last_error = f"部分文档索引失败: {doc_exc}"
                continue

        ds.status = DataSourceStatus.ready
        ds.doc_count = indexed
        ds.last_synced_at = datetime.utcnow()
        ds.sync_cursor = json.dumps(cursor)
        if not failed:
            ds.last_error = None
    except Exception as exc:
        ds = db.get(DataSource, ds_id)
        if ds:
            ds.status = DataSourceStatus.error
            ds.last_error = str(exc)
    finally:
        db.commit()
        db.close()


async def _run_incremental_sync(ds_id: int) -> None:
    """Incremental sync: upsert new/changed documents since last cursor.

    Delete-then-add ensures stale chunks from updated rows are never left behind.
    """
    from src.core.database import SessionLocal
    from src.core.vector_store import add_document, delete_document

    db = SessionLocal()
    try:
        ds = db.get(DataSource, ds_id)
        if not ds:
            return
        if ds.status == DataSourceStatus.syncing:
            return  # full sync in progress, skip

        ds.status = DataSourceStatus.syncing
        db.commit()

        connector = _make_connector(ds)
        cursor = json.loads(ds.sync_cursor) if ds.sync_cursor else {}
        actual_col = _actual_col(ds)

        docs, new_cursor = await connector.sync_incremental(cursor)

        indexed = 0
        for doc in docs:
            try:
                # Remove old chunks first so count changes don't leave ghost chunks
                delete_document(doc.doc_id, actual_col)
                add_document(doc, actual_col)
                indexed += 1
            except Exception:
                continue

        ds.status = DataSourceStatus.ready
        ds.doc_count = (ds.doc_count or 0) + indexed
        ds.last_synced_at = datetime.utcnow()
        ds.sync_cursor = json.dumps(new_cursor)
        if indexed > 0:
            ds.last_error = None
    except Exception as exc:
        ds = db.get(DataSource, ds_id)
        if ds:
            ds.status = DataSourceStatus.error
            ds.last_error = str(exc)
    finally:
        db.commit()
        db.close()
