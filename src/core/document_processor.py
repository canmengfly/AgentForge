from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO


@dataclass
class DocumentChunk:
    chunk_id: str
    doc_id: str
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    doc_id: str
    title: str
    source: str
    content: str
    metadata: dict = field(default_factory=dict)


def _make_id(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def parse_text(content: str, title: str, source: str = "inline") -> ParsedDocument:
    doc_id = _make_id(title + content[:100])
    return ParsedDocument(doc_id=doc_id, title=title, source=source, content=content)


def parse_pdf(file: BinaryIO, filename: str) -> ParsedDocument:
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("pdfplumber required: pip install pdfplumber") from e

    pages = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    content = "\n\n".join(pages)
    doc_id = _make_id(filename + content[:100])
    return ParsedDocument(
        doc_id=doc_id,
        title=Path(filename).stem,
        source=filename,
        content=content,
        metadata={"page_count": len(pages)},
    )


def parse_docx(file: BinaryIO, filename: str) -> ParsedDocument:
    try:
        from docx import Document
    except ImportError as e:
        raise RuntimeError("python-docx required: pip install python-docx") from e

    doc = Document(file)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    content = "\n\n".join(paragraphs)
    doc_id = _make_id(filename + content[:100])
    return ParsedDocument(
        doc_id=doc_id,
        title=Path(filename).stem,
        source=filename,
        content=content,
    )


def parse_html(content: str | bytes, filename: str) -> ParsedDocument:
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise RuntimeError("beautifulsoup4 required: pip install beautifulsoup4") from e

    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else Path(filename).stem
    doc_id = _make_id(filename + text[:100])
    return ParsedDocument(doc_id=doc_id, title=title, source=filename, content=text)


def parse_file(file: BinaryIO, filename: str) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(file, filename)
    if suffix == ".docx":
        return parse_docx(file, filename)
    if suffix in (".html", ".htm"):
        return parse_html(file.read(), filename)
    # Plain text / markdown
    raw = file.read()
    content = raw.decode("utf-8", errors="replace")
    doc_id = _make_id(filename + content[:100])
    return ParsedDocument(
        doc_id=doc_id,
        title=Path(filename).stem,
        source=filename,
        content=content,
    )


def chunk_document(doc: ParsedDocument, chunk_size: int = 512, overlap: int = 64) -> list[DocumentChunk]:
    text = doc.content
    chunks: list[DocumentChunk] = []
    separators = ["\n\n", "\n", ". ", " ", ""]

    def _split(text: str, sep_idx: int = 0) -> list[str]:
        if len(text) <= chunk_size or sep_idx >= len(separators):
            return [text]
        sep = separators[sep_idx]
        parts = text.split(sep) if sep else list(text)
        result: list[str] = []
        current = ""
        for part in parts:
            candidate = current + (sep if current else "") + part
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    result.append(current)
                if len(part) > chunk_size:
                    result.extend(_split(part, sep_idx + 1))
                    current = ""
                else:
                    current = part
        if current:
            result.append(current)
        return result

    raw_chunks = _split(text)

    # Apply overlap by prepending tail of previous chunk
    for i, chunk_text in enumerate(raw_chunks):
        if i > 0 and overlap > 0:
            prev = raw_chunks[i - 1]
            prefix = prev[-overlap:].lstrip()
            chunk_text = prefix + " " + chunk_text if prefix else chunk_text

        chunk_id = _make_id(doc.doc_id + str(i))
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                content=chunk_text.strip(),
                metadata={
                    **doc.metadata,
                    "title": doc.title,
                    "source": doc.source,
                    "chunk_index": i,
                    "total_chunks": len(raw_chunks),
                },
            )
        )
    return chunks
