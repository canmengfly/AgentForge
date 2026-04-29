from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


class APIToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DataSourceType(str, enum.Enum):
    # Object storage
    oss = "oss"
    s3 = "s3"
    tencent_cos = "tencent_cos"
    huawei_obs = "huawei_obs"
    # Relational / OLAP
    mysql = "mysql"
    postgres = "postgres"
    oracle = "oracle"
    sqlserver = "sqlserver"
    tidb = "tidb"
    oceanbase = "oceanbase"
    doris = "doris"
    clickhouse = "clickhouse"
    hive = "hive"
    snowflake = "snowflake"
    # Search / NoSQL
    elasticsearch = "elasticsearch"
    mongodb = "mongodb"
    # Document platforms
    feishu = "feishu"
    dingtalk = "dingtalk"
    tencent_docs = "tencent_docs"
    confluence = "confluence"
    notion = "notion"
    yuque = "yuque"
    # Code platforms
    github = "github"
    gitlab = "gitlab"
    # Enterprise cloud
    sharepoint = "sharepoint"
    google_drive = "google_drive"


class DataSourceStatus(str, enum.Enum):
    idle = "idle"
    syncing = "syncing"
    ready = "ready"
    error = "error"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[DataSourceType] = mapped_column(Enum(DataSourceType), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    collection: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DataSourceStatus] = mapped_column(
        Enum(DataSourceStatus), default=DataSourceStatus.idle, nullable=False
    )
    doc_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sync_interval: Mapped[int | None] = mapped_column(Integer, nullable=True)   # minutes; None = disabled
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON incremental cursor

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "collection": self.collection,
            "status": self.status.value,
            "doc_count": self.doc_count,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat(),
            "sync_interval": self.sync_interval,
        }


class SystemConfig(Base):
    """Key-value store for persistent system-level settings."""
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
