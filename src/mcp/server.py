"""MCP server for the Agent Knowledge Platform.

Run standalone:
    python -m src.mcp.server

Or add to Claude Desktop / Claude Code settings.json:
    {
      "mcpServers": {
        "knowledge": {
          "command": "python",
          "args": ["-m", "src.mcp.server"],
          "env": { "AFT_API_BASE": "http://localhost:8000" }
        }
      }
    }
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

API_BASE = os.environ.get("AFT_API_BASE", "http://localhost:8000")

server = Server("agent-knowledge-platform")


def _client() -> httpx.Client:
    headers = {}
    api_key = os.environ.get("AFT_API_KEY", "")
    if api_key:
        headers["X-API-Key"] = api_key
    return httpx.Client(base_url=API_BASE, headers=headers, timeout=30)


def _ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))])


def _err(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"Error: {msg}")], isError=True)


@server.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="search_knowledge",
                description=(
                    "Semantically search the knowledge base for relevant document chunks. "
                    "Returns ranked results with content and source metadata. "
                    "Use this to retrieve context before answering domain-specific questions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query"},
                        "collection": {"type": "string", "default": "default", "description": "Collection to search"},
                        "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20,
                                  "description": "Number of results to return"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="list_collections",
                description="List all document collections and their document chunk counts.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="add_text_document",
                description=(
                    "Add a text document to the knowledge base. "
                    "Use this to store new information that should be searchable later."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Document title"},
                        "content": {"type": "string", "description": "Document content (plain text or markdown)"},
                        "collection": {"type": "string", "default": "default"},
                        "metadata": {"type": "object", "description": "Optional key-value metadata"},
                    },
                    "required": ["title", "content"],
                },
            ),
            Tool(
                name="get_document_chunks",
                description="Retrieve all chunks of a specific document by its ID.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Document ID returned when the document was added"},
                        "collection": {"type": "string", "default": "default"},
                    },
                    "required": ["doc_id"],
                },
            ),
            Tool(
                name="delete_document",
                description="Delete a document and all its chunks from the knowledge base.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "collection": {"type": "string", "default": "default"},
                    },
                    "required": ["doc_id"],
                },
            ),
        ]
    )


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        with _client() as client:
            if name == "search_knowledge":
                resp = client.post("/search", json={
                    "query": arguments["query"],
                    "collection": arguments.get("collection", "default"),
                    "top_k": arguments.get("top_k", 5),
                })
                resp.raise_for_status()
                data = resp.json()
                # Format hits as readable text blocks
                hits = data.get("hits", [])
                if not hits:
                    return _ok({"message": "No relevant documents found.", "query": arguments["query"]})
                formatted = []
                for i, hit in enumerate(hits, 1):
                    meta = hit.get("metadata", {})
                    formatted.append({
                        "rank": i,
                        "score": hit["score"],
                        "title": meta.get("title", "Unknown"),
                        "source": meta.get("source", ""),
                        "chunk": f"{meta.get('chunk_index', 0) + 1}/{meta.get('total_chunks', 1)}",
                        "content": hit["content"],
                    })
                return _ok({"query": arguments["query"], "results": formatted})

            elif name == "list_collections":
                resp = client.get("/collections")
                resp.raise_for_status()
                return _ok(resp.json())

            elif name == "add_text_document":
                resp = client.post("/documents/text", json={
                    "title": arguments["title"],
                    "content": arguments["content"],
                    "collection": arguments.get("collection", "default"),
                    "metadata": arguments.get("metadata", {}),
                })
                resp.raise_for_status()
                return _ok(resp.json())

            elif name == "get_document_chunks":
                doc_id = arguments["doc_id"]
                collection = arguments.get("collection", "default")
                resp = client.get(f"/documents/{doc_id}/chunks", params={"collection": collection})
                resp.raise_for_status()
                return _ok(resp.json())

            elif name == "delete_document":
                doc_id = arguments["doc_id"]
                collection = arguments.get("collection", "default")
                resp = client.delete(f"/documents/{doc_id}", params={"collection": collection})
                resp.raise_for_status()
                return _ok(resp.json())

            else:
                return _err(f"Unknown tool: {name}")

    except httpx.HTTPStatusError as e:
        return _err(f"API error {e.response.status_code}: {e.response.text}")
    except httpx.ConnectError:
        return _err(f"Cannot connect to knowledge platform at {API_BASE}. Is the API server running?")
    except Exception as e:
        return _err(str(e))


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run():
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    run()
