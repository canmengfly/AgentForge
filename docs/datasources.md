# Data Source Connectors

AgentForge supports 27 external data source types. This document covers configuration fields, authentication requirements, and sync behavior for each connector.

---

## Table of Contents

- [Object Storage](#object-storage)
  - [Alibaba Cloud OSS](#alibaba-cloud-oss)
  - [Amazon S3](#amazon-s3)
  - [Tencent Cloud COS](#tencent-cloud-cos)
  - [Huawei Cloud OBS](#huawei-cloud-obs)
- [Relational Databases](#relational-databases)
  - [MySQL](#mysql)
  - [PostgreSQL](#postgresql)
  - [Oracle](#oracle)
  - [SQL Server](#sql-server)
  - [TiDB](#tidb)
  - [OceanBase](#oceanbase)
- [OLAP / Data Warehouse](#olap--data-warehouse)
  - [Apache Doris](#apache-doris)
  - [ClickHouse](#clickhouse)
  - [Apache Hive](#apache-hive)
  - [Snowflake](#snowflake)
- [Search / NoSQL](#search--nosql)
  - [Elasticsearch](#elasticsearch)
  - [MongoDB](#mongodb)
- [Document Platforms](#document-platforms)
  - [Feishu (Lark) Docs](#feishu-lark-docs)
  - [DingTalk Docs](#dingtalk-docs)
  - [Tencent Docs](#tencent-docs)
  - [Confluence](#confluence)
  - [Notion](#notion)
  - [Yuque](#yuque)
- [Code Platforms](#code-platforms)
  - [GitHub](#github)
  - [GitLab](#gitlab)
- [Enterprise Cloud](#enterprise-cloud)
  - [Microsoft SharePoint](#microsoft-sharepoint)
  - [Google Drive](#google-drive)

---

## Object Storage

### Alibaba Cloud OSS

**Required package:** `oss2>=2.18.0`

| Field | Type | Description |
|---|---|---|
| `access_key_id` | string | AccessKey ID |
| `access_key_secret` | string | AccessKey Secret |
| `endpoint` | string | OSS endpoint, e.g. `oss-cn-hangzhou.aliyuncs.com` |
| `bucket` | string | Bucket name |
| `prefix` | string | Optional key prefix to filter objects |

**Incremental sync:** uses `LastModified` timestamp.

---

### Amazon S3

**Required package:** `boto3>=1.34.0`

| Field | Type | Description |
|---|---|---|
| `access_key_id` | string | AWS access key ID |
| `secret_access_key` | string | AWS secret access key |
| `bucket` | string | S3 bucket name |
| `region` | string | AWS region, e.g. `us-east-1` |
| `prefix` | string | Optional key prefix |
| `endpoint_url` | string | Custom endpoint for S3-compatible storage |

**Incremental sync:** uses `LastModified` timestamp.

---

### Tencent Cloud COS

**Required package:** `cos-python-sdk-v5>=1.9.0`

| Field | Type | Description |
|---|---|---|
| `secret_id` | string | Tencent Cloud SecretId |
| `secret_key` | string | Tencent Cloud SecretKey |
| `bucket` | string | Bucket name (including appid, e.g. `my-bucket-1250000000`) |
| `region` | string | Region, e.g. `ap-beijing` |
| `prefix` | string | Optional key prefix |

**Incremental sync:** uses `LastModified` ISO 8601 timestamp.

---

### Huawei Cloud OBS

**Required package:** `esdk-obs-python>=3.24.0`

| Field | Type | Description |
|---|---|---|
| `access_key_id` | string | AK (Access Key) |
| `secret_access_key` | string | SK (Secret Key) |
| `endpoint` | string | OBS endpoint, e.g. `obs.cn-north-4.myhuaweicloud.com` |
| `bucket` | string | Bucket name |
| `prefix` | string | Optional key prefix |

**Incremental sync:** uses `LastModified` timestamp.

---

## Relational Databases

All SQL connectors discover tables automatically (or use the `tables` field to restrict) and convert each row into a text document. Row content is formatted as `key: value` pairs, truncated at 500 characters per field.

### MySQL

**Required package:** `PyMySQL>=1.1.0`

| Field | Type | Description |
|---|---|---|
| `host` | string | Hostname or IP |
| `port` | int | Default: `3306` |
| `database` | string | Database name |
| `username` | string | MySQL user |
| `password` | string | MySQL password |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

**Incremental sync:** full re-sync (no change tracking).

---

### PostgreSQL

**Required package:** `psycopg2-binary>=2.9.0`

| Field | Type | Description |
|---|---|---|
| `host` | string | Hostname or IP |
| `port` | int | Default: `5432` |
| `database` | string | Database name |
| `username` | string | PostgreSQL user |
| `password` | string | PostgreSQL password |
| `schema` | string | Schema to query (default: `public`) |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

**Incremental sync:** full re-sync.

---

### Oracle

**Required package:** `oracledb>=2.0.0`

Uses `oracledb` in thin mode — no Oracle Client installation required.

| Field | Type | Description |
|---|---|---|
| `host` | string | Hostname or IP |
| `port` | int | Default: `1521` |
| `service_name` | string | Oracle service name (preferred) |
| `sid` | string | Oracle SID (alternative to service_name) |
| `username` | string | Oracle user |
| `password` | string | Oracle password |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

Table discovery uses `user_tables`. Query uses `FETCH FIRST N ROWS ONLY` syntax.

**Incremental sync:** full re-sync.

---

### SQL Server

**Required package:** `pymssql>=2.2.0`

| Field | Type | Description |
|---|---|---|
| `host` | string | Hostname or IP |
| `port` | int | Default: `1433` |
| `database` | string | Database name |
| `username` | string | SQL Server login |
| `password` | string | SQL Server password |
| `schema` | string | Schema name (default: `dbo`) |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

Table discovery uses `INFORMATION_SCHEMA.TABLES`. Query uses `SELECT TOP N` syntax.

**Incremental sync:** full re-sync.

---

### TiDB

**Required package:** `PyMySQL>=1.1.0`

TiDB is MySQL-compatible. Uses the MySQL connector internally with a default port of `4000`.

| Field | Type | Description |
|---|---|---|
| `host` | string | TiDB host |
| `port` | int | Default: `4000` |
| `database` | string | Database name |
| `username` | string | TiDB user |
| `password` | string | TiDB password |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

---

### OceanBase

**Required package:** `PyMySQL>=1.1.0`

OceanBase is MySQL-compatible. Uses the MySQL connector internally with a default port of `2881`.

| Field | Type | Description |
|---|---|---|
| `host` | string | OceanBase host |
| `port` | int | Default: `2881` |
| `database` | string | Database name |
| `username` | string | OceanBase user |
| `password` | string | OceanBase password |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

---

## OLAP / Data Warehouse

### Apache Doris

**Required package:** `PyMySQL>=1.1.0`

Apache Doris exposes a MySQL-compatible interface. Uses the MySQL connector with a default port of `9030`.

| Field | Type | Description |
|---|---|---|
| `host` | string | Doris FE host |
| `port` | int | Default: `9030` |
| `database` | string | Database name |
| `username` | string | Doris user |
| `password` | string | Doris password |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

---

### ClickHouse

**Required package:** `clickhouse-connect>=0.7.0`

| Field | Type | Description |
|---|---|---|
| `host` | string | ClickHouse host |
| `port` | int | Default: `8123` (HTTP interface) |
| `database` | string | Database name |
| `username` | string | ClickHouse user |
| `password` | string | ClickHouse password |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |
| `secure` | bool | Use HTTPS (default: `false`) |

Table discovery uses `system.tables` filtered by database.

---

### Apache Hive

**Required packages:** `pyhive[hive]>=0.7.0`, `thrift>=0.16.0`

| Field | Type | Description |
|---|---|---|
| `host` | string | HiveServer2 host |
| `port` | int | Default: `10000` |
| `database` | string | Hive database name |
| `username` | string | Hive user |
| `password` | string | Optional password (for LDAP auth) |
| `auth` | string | Authentication method: `NONE`, `LDAP`, or `NOSASL` (default: `NONE`) |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

---

### Snowflake

**Required package:** `snowflake-sqlalchemy>=1.5.0`

| Field | Type | Description |
|---|---|---|
| `account` | string | Snowflake account identifier (e.g. `myorg-myaccount`) |
| `user` | string | Snowflake username |
| `password` | string | Snowflake password |
| `database` | string | Database name |
| `schema` | string | Schema name (default: `PUBLIC`) |
| `warehouse` | string | Snowflake virtual warehouse |
| `tables` | list | Optional: restrict to specific tables |
| `row_limit` | int | Max rows per table (default: `5000`) |

Connection uses SQLAlchemy with the `snowflake` dialect. Table discovery uses `INFORMATION_SCHEMA.TABLES`.

---

## Search / NoSQL

### Elasticsearch

**Required package:** `elasticsearch>=8.0.0`

| Field | Type | Description |
|---|---|---|
| `hosts` | list | ES hosts, e.g. `["http://localhost:9200"]` |
| `username` | string | Optional: Basic auth username |
| `password` | string | Optional: Basic auth password |
| `api_key` | string | Optional: API key (alternative to username/password) |
| `indices` | list | Optional: restrict to specific indices |
| `text_fields` | list | Fields to extract text from (default: common fields) |
| `size` | int | Max documents per index (default: `1000`) |
| `verify_certs` | bool | Verify TLS certificates (default: `true`) |

Documents are searched using `match_all` and text is assembled from specified `text_fields`.

**Incremental sync:** uses `_source` field `updated_at` or `@timestamp` if present.

---

### MongoDB

**Required package:** `pymongo>=4.6.0`

| Field | Type | Description |
|---|---|---|
| `host` | string | MongoDB host (default: `localhost`) |
| `port` | int | Default: `27017` |
| `database` | string | Database name |
| `username` | string | Optional: MongoDB user |
| `password` | string | Optional: MongoDB password |
| `collections` | list | Optional: restrict to specific collections |
| `row_limit` | int | Max documents per collection (default: `5000`) |

**Incremental sync:** full re-sync.

---

## Document Platforms

### Feishu (Lark) Docs

| Field | Type | Description |
|---|---|---|
| `app_id` | string | Feishu App ID |
| `app_secret` | string | Feishu App Secret |
| `folder_token` | string | Optional: root folder token to restrict scope |

Uses the Feishu Open API. Fetches document trees and exports doc content as plain text.

**Incremental sync:** uses `edit_time` Unix timestamp.

---

### DingTalk Docs

| Field | Type | Description |
|---|---|---|
| `app_key` | string | DingTalk AppKey |
| `app_secret` | string | DingTalk AppSecret |
| `space_id` | string | Optional: knowledge space ID |

Uses the DingTalk Open API to list and fetch documents.

**Incremental sync:** uses `modifiedTime` timestamp.

---

### Tencent Docs

| Field | Type | Description |
|---|---|---|
| `access_token` | string | Tencent Docs OAuth access token |
| `folder_id` | string | Optional: root folder ID |

Uses the Tencent Docs Open API.

**Incremental sync:** uses `updateTime` timestamp.

---

### Confluence

**Required package:** `beautifulsoup4>=4.12.0`

| Field | Type | Description |
|---|---|---|
| `base_url` | string | Confluence base URL, e.g. `https://mycompany.atlassian.net` |
| `username` | string | Atlassian account email (Cloud) or username (Server) |
| `api_token` | string | Atlassian API token (Cloud) or password (Server) |
| `is_cloud` | bool | `true` for Confluence Cloud, `false` for Server/DC |
| `space_keys` | list | Optional: restrict to specific space keys |

Cloud adds `/wiki` prefix to all API paths. Pages are listed per space with pagination. HTML body is stripped with BeautifulSoup.

**Incremental sync:** uses `history.lastUpdated.when` ISO timestamp.

---

### Notion

| Field | Type | Description |
|---|---|---|
| `token` | string | Notion Integration token (`secret_...`) |
| `database_ids` | list | Optional: specific database IDs to query |

Searches all pages via Notion API or queries specific databases. Block content is fetched recursively (up to depth 3). Rich text arrays are flattened to plain text.

**Incremental sync:** uses `last_edited_time` ISO timestamp.

---

### Yuque

| Field | Type | Description |
|---|---|---|
| `token` | string | Yuque personal access token |
| `namespace` | string | Optional: team/user namespace slug (e.g. `myteam`) |
| `base_url` | string | Base URL for private deployments (default: `https://www.yuque.com/api/v2`) |

Fetches repositories under the namespace (or all accessible repos), then fetches each document's HTML body and strips it with BeautifulSoup.

**Incremental sync:** uses `updated_at` ISO timestamp.

---

## Code Platforms

### GitHub

| Field | Type | Description |
|---|---|---|
| `token` | string | GitHub personal access token (or fine-grained token) |
| `repos` | list | Repository names in `owner/repo` format |
| `branch` | string | Branch to index (default: `main`) |
| `path_prefix` | string | Optional: limit to a subdirectory (e.g. `docs/`) |
| `file_types` | list | File extensions to index (default: `[".md", ".txt", ".py"]`) |
| `base_url` | string | GitHub Enterprise API URL (default: `https://api.github.com`) |

Fetches the commit tree for the branch, filters files by extension and path prefix, decodes base64 content, and indexes each file as a document.

**Incremental sync:** full re-sync.

---

### GitLab

| Field | Type | Description |
|---|---|---|
| `token` | string | GitLab personal access token |
| `projects` | list | Project paths in `namespace/project` format |
| `branch` | string | Branch to index (default: `main`) |
| `path_prefix` | string | Optional: limit to a subdirectory |
| `file_types` | list | File extensions to index (default: `[".md", ".txt", ".py"]`) |
| `base_url` | string | GitLab instance URL (default: `https://gitlab.com`) |

Uses the GitLab REST API with `PRIVATE-TOKEN` header. Project paths with spaces are URL-encoded.

**Incremental sync:** full re-sync.

---

## Enterprise Cloud

### Microsoft SharePoint

**Required packages:** `msal>=1.24.0`, `httpx>=0.27.0`

| Field | Type | Description |
|---|---|---|
| `tenant_id` | string | Azure AD tenant ID |
| `client_id` | string | Azure app client ID |
| `client_secret` | string | Azure app client secret |
| `site_url` | string | SharePoint site URL |
| `folder_path` | string | Optional: restrict to a specific folder path |

Uses Microsoft Graph API with `client_credentials` OAuth flow. The site URL is resolved to a Graph site ID, then drive items are listed and file content is downloaded and parsed.

**Supported file types:** TXT, MD, HTML, PDF, DOCX (via `document_processor.parse_file`).

**Incremental sync:** full re-sync.

---

### Google Drive

**Required packages:** `google-api-python-client>=2.100.0`, `google-auth>=2.23.0`

| Field | Type | Description |
|---|---|---|
| `credentials_json` | string | Service account JSON (as string or file path) |
| `folder_id` | string | Optional: restrict to a specific folder ID |

Uses a Google service account. Google Docs are exported as `text/plain`, Google Sheets as `text/csv`. Other supported MIME types are downloaded as binary and parsed.

**Credentials:** can be passed as either a raw JSON string (starting with `{`) or a file path to a service account JSON file.

**Incremental sync:** uses `modifiedTime > '{since_iso}'` in the Drive API query.

---

## Optional Dependency Installation

Install only the packages you need:

```bash
# Object storage
pip install oss2 boto3 cos-python-sdk-v5 esdk-obs-python

# Relational / OLAP
pip install PyMySQL psycopg2-binary oracledb pymssql snowflake-sqlalchemy

# Search / NoSQL
pip install elasticsearch pymongo clickhouse-connect

# Hive
pip install "pyhive[hive]" thrift

# Enterprise cloud
pip install google-api-python-client google-auth msal

# Scheduler
pip install APScheduler
```

Or install everything at once:

```bash
pip install agentf[all]
```
