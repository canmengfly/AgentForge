# Deployment Guide

This guide covers production deployment options for AgentForge.

---

## Requirements

- Python 3.11+
- 2 GB RAM minimum (more if using a large embedding or reranker model)
- Persistent storage for ChromaDB and SQLite (or a PostgreSQL instance for pgvector)

---

## Environment Variables

Create a `.env` file in the working directory:

```env
# Required
JWT_SECRET=replace-with-a-random-64-char-string

# Storage
DATA_DIR=/var/agentforge/data

# Vector backend (chroma is default)
VECTOR_BACKEND=chroma
# VECTOR_BACKEND=pgvector
# PG_VECTOR_URL=postgresql://agentforge:password@localhost/agentforge

# Embedding model
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIM=384

# Optional: cross-encoder reranker (comment out to disable)
# RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2

# Session
JWT_EXPIRE_MINUTES=10080
```

Generate a strong JWT secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Option 1: systemd Service

### 1. Install

```bash
pip install agentf
```

### 2. Create service file

```ini
# /etc/systemd/system/agentforge.service
[Unit]
Description=AgentForge API
After=network.target

[Service]
Type=simple
User=agentforge
WorkingDirectory=/var/agentforge
EnvironmentFile=/var/agentforge/.env
ExecStart=/usr/local/bin/agentf-api
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. Enable and start

```bash
sudo useradd -r -s /bin/false agentforge
sudo mkdir -p /var/agentforge/data
sudo chown agentforge:agentforge /var/agentforge
sudo systemctl daemon-reload
sudo systemctl enable --now agentforge
```

### 4. Verify

```bash
sudo systemctl status agentforge
journalctl -u agentforge -f
```

---

## Option 2: Docker

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install agentf

ENV DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

CMD ["agentf-api"]
```

### Build and run

```bash
docker build -t agentforge .

docker run -d \
  --name agentforge \
  -p 8000:8000 \
  -v agentforge_data:/data \
  -e JWT_SECRET=your-secret-here \
  -e EMBEDDING_MODEL=all-MiniLM-L6-v2 \
  agentforge
```

### docker-compose.yml

```yaml
services:
  agentforge:
    image: agentforge
    build: .
    ports:
      - "8000:8000"
    volumes:
      - agentforge_data:/data
    env_file:
      - .env
    restart: unless-stopped

  # Optional: PostgreSQL for pgvector backend
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: agentforge
      POSTGRES_USER: agentforge
      POSTGRES_PASSWORD: changeme
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  agentforge_data:
  pg_data:
```

---

## Option 3: Reverse Proxy (Nginx)

Place AgentForge behind Nginx for TLS termination:

```nginx
server {
    listen 443 ssl;
    server_name agentforge.example.com;

    ssl_certificate     /etc/letsencrypt/live/agentforge.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/agentforge.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Needed for file uploads
        client_max_body_size 50m;
    }
}

server {
    listen 80;
    server_name agentforge.example.com;
    return 301 https://$host$request_uri;
}
```

---

## pgvector Backend

### PostgreSQL setup

```bash
# Install pgvector (Ubuntu/Debian)
sudo apt install postgresql-16-pgvector

# Or using Docker
docker run -d \
  --name pgvector \
  -e POSTGRES_DB=agentforge \
  -e POSTGRES_USER=agentforge \
  -e POSTGRES_PASSWORD=changeme \
  pgvector/pgvector:pg16
```

Enable the extension:
```sql
-- Connect to the agentforge database
CREATE EXTENSION IF NOT EXISTS vector;
```

### Configure AgentForge

```env
VECTOR_BACKEND=pgvector
PG_VECTOR_URL=postgresql://agentforge:changeme@localhost/agentforge
EMBEDDING_DIM=384
```

The table `document_chunks` and HNSW cosine index are created automatically on first startup.

---

## Embedding Models

Models are downloaded from Hugging Face on first use and cached locally. To pre-download:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Model size reference

| Model | Embedding Dim | Download Size | Latency |
|---|---|---|---|
| `all-MiniLM-L6-v2` | 384 | ~92 MB | Fast |
| `all-MiniLM-L12-v2` | 384 | ~120 MB | Medium |
| `all-mpnet-base-v2` | 768 | ~420 MB | Slower |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | ~471 MB | Medium |

If you change `EMBEDDING_MODEL`, you must also update `EMBEDDING_DIM` and re-index all documents, as stored vectors are not compatible across models.

---

## Security Checklist

- [ ] Set a strong, random `JWT_SECRET` (64+ characters)
- [ ] Change the default admin password immediately after first login
- [ ] Run behind a reverse proxy with TLS in production
- [ ] Do not expose port 8000 directly to the internet
- [ ] Restrict `DATA_DIR` permissions to the service user (`chmod 700`)
- [ ] Use read-only database credentials for SQL data source connectors where possible
- [ ] Review data source credentials — they are stored encrypted in SQLite but protect your `.env` and database files

---

## Backup

### ChromaDB + SQLite

```bash
# Stop the service first for a consistent snapshot
systemctl stop agentforge

# Backup
tar -czf agentforge-backup-$(date +%Y%m%d).tar.gz /var/agentforge/data

# Restart
systemctl start agentforge
```

### pgvector

```bash
pg_dump -U agentforge agentforge > agentforge-$(date +%Y%m%d).sql
```

---

## Upgrading

```bash
pip install --upgrade agentf
systemctl restart agentforge
```

Database migrations (if any) run automatically on startup.
