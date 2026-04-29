"""Google Drive connector — service account credentials, exports Docs as plain text."""
from __future__ import annotations

import asyncio
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id, parse_file

_EXPORT_MIME = "text/plain"
_GDOC_MIME = "application/vnd.google-apps.document"
_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
_EXPORT_SHEET = "text/csv"
_SUPPORTED_MIME = {
    "text/plain", "text/markdown", "text/html",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
}


@dataclass
class GoogleDriveConfig:
    credentials_json: str     # service account JSON as string, or path to JSON file
    folder_id: str = ""       # specific folder ID; empty = shared drive root
    file_types: list[str] = field(default_factory=list)   # MIME type filters (empty = defaults)


class GoogleDriveConnector:
    def __init__(self, config: GoogleDriveConfig):
        self.config = config

    def _build_service(self):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as e:
            raise RuntimeError(
                "google-api-python-client and google-auth required: "
                "pip install google-api-python-client google-auth"
            ) from e

        creds_data = self.config.credentials_json.strip()
        if creds_data.startswith("{"):
            info = json.loads(creds_data)
        else:
            with open(creds_data) as f:
                info = json.load(f)

        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _test_sync(self) -> dict:
        try:
            svc = self._build_service()
            svc.files().list(pageSize=1, fields="files(id)").execute()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _list_files(self, svc, since_iso: str | None) -> list[dict]:
        query_parts = ["trashed = false"]
        if self.config.folder_id:
            query_parts.append(f"'{self.config.folder_id}' in parents")
        if since_iso:
            query_parts.append(f"modifiedTime > '{since_iso}'")
        q = " and ".join(query_parts)

        files: list[dict] = []
        page_token = None
        while True:
            params: dict = {
                "q": q,
                "fields": "nextPageToken, files(id,name,mimeType,modifiedTime)",
                "pageSize": 200,
            }
            if page_token:
                params["pageToken"] = page_token
            result = svc.files().list(**params).execute()
            files.extend(result.get("files", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return files

    def _fetch_file(self, svc, file: dict) -> bytes | None:
        mime = file.get("mimeType", "")
        fid = file["id"]
        try:
            if mime == _GDOC_MIME:
                resp = svc.files().export(fileId=fid, mimeType=_EXPORT_MIME).execute()
                return resp if isinstance(resp, bytes) else resp.encode()
            if mime == _SHEET_MIME:
                resp = svc.files().export(fileId=fid, mimeType=_EXPORT_SHEET).execute()
                return resp if isinstance(resp, bytes) else resp.encode()
            if mime in _SUPPORTED_MIME:
                import googleapiclient.http
                buf = io.BytesIO()
                req = svc.files().get_media(fileId=fid)
                downloader = googleapiclient.http.MediaIoBaseDownload(buf, req)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return buf.getvalue()
        except Exception:
            return None
        return None

    def _collect(self, since_iso: str | None) -> tuple[list[ParsedDocument], dict]:
        svc = self._build_service()
        files = self._list_files(svc, since_iso)
        docs: list[ParsedDocument] = []
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        for f in files:
            raw = self._fetch_file(svc, f)
            if not raw:
                continue
            name: str = f.get("name", "file")
            # Treat Google Docs exports as .txt
            fake_name = name if "." in name else name + ".txt"
            try:
                doc = parse_file(io.BytesIO(raw), fake_name)
                doc.doc_id = _make_id(f"gdrive:{f['id']}")
                doc.source = f"https://drive.google.com/file/d/{f['id']}/view"
                doc.metadata.update({
                    "source_type": "google_drive",
                    "file_id": f["id"],
                    "mime_type": f.get("mimeType", ""),
                })
                docs.append(doc)
            except Exception:
                continue

        return docs, {"last_iso": now_iso}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, None)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, cursor.get("last_iso"))
