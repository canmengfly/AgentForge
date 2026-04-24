"""Endpoints that generate ready-to-use configs for Claude MCP, Hermes, and OpenLCAW agents."""
from __future__ import annotations

import json
import textwrap

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from src.core.vector_store import list_collections

router = APIRouter(prefix="/export", tags=["export"])

# ── Shared tool schema ────────────────────────────────────────────────────────

def _tool_schemas(base_url: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": (
                    "Semantically search the personal knowledge base for relevant document chunks. "
                    "Use this before answering questions that may require domain-specific knowledge."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query",
                        },
                        "collection": {
                            "type": "string",
                            "description": "Collection name to search (default: 'default')",
                            "default": "default",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return (1-20)",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_collections",
                "description": "List all document collections and their chunk counts.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_text_document",
                "description": "Add a text document to the knowledge base so it can be searched later.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Document title"},
                        "content": {
                            "type": "string",
                            "description": "Document content (plain text or markdown)",
                        },
                        "collection": {
                            "type": "string",
                            "description": "Target collection name",
                            "default": "default",
                        },
                    },
                    "required": ["title", "content"],
                },
            },
        },
    ]


def _api_impl_block(base_url: str) -> dict:
    return {
        "api_base": base_url,
        "auth": {
            "method": "bearer",
            "obtain_token": f"POST {base_url}/auth/token",
            "token_body": '{"username": "<your_username>", "password": "<your_password>"}',
            "usage": "Authorization: Bearer <access_token>",
        },
        "endpoints": {
            "search": f"POST {base_url}/me/search",
            "list_collections": f"GET {base_url}/me/collections",
            "add_text": f"POST {base_url}/me/documents/text",
        },
    }


# ── MCP (Claude Desktop / Claude Code) ───────────────────────────────────────

@router.get("/mcp-config")
async def get_mcp_config(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return {
        "mcpServers": {
            "knowledge": {
                "command": "agentf-mcp",
                "args": [],
                "env": {"AFT_API_BASE": base_url},
            }
        }
    }


@router.get("/claude-settings")
async def get_claude_settings(request: Request):
    base_url = str(request.base_url).rstrip("/")
    snippet = {
        "mcpServers": {
            "knowledge": {
                "command": "agentf-mcp",
                "args": [],
                "env": {"AFT_API_BASE": base_url},
            }
        }
    }
    return {"settings_snippet": snippet, "hint": "Merge this into your ~/.claude/settings.json"}


# ── Claude Code Skills ────────────────────────────────────────────────────────

@router.get("/skill/{skill_name}", response_class=PlainTextResponse)
async def get_skill(skill_name: str, request: Request):
    base_url = str(request.base_url).rstrip("/")
    skills = _build_skills(base_url)
    if skill_name not in skills:
        from fastapi import HTTPException
        raise HTTPException(404, f"Skill '{skill_name}' not found. Available: {list(skills)}")
    return skills[skill_name]


@router.get("/skills")
async def list_skills(request: Request):
    base_url = str(request.base_url).rstrip("/")
    skills = _build_skills(base_url)
    return {
        "skills": [
            {"name": name, "url": f"{base_url}/export/skill/{name}"}
            for name in skills
        ]
    }


def _build_skills(base_url: str) -> dict[str, str]:
    collections = [c["name"] for c in list_collections()] or ["default"]
    col_list = ", ".join(f'"{c}"' for c in collections)

    search_skill = textwrap.dedent(f"""\
        ---
        description: Search the knowledge base for relevant context. Use this before answering questions that may require specific domain knowledge or documents uploaded by the user.
        ---

        Search the knowledge platform at {base_url} for context relevant to: ${{ARGUMENTS}}

        Steps:
        1. Call POST {base_url}/me/search with body:
           ```json
           {{
             "query": "<your search query>",
             "collection": "default",
             "top_k": 5
           }}
           ```
        2. Review the returned `hits` ranked by `score` (0–1, higher is better)
        3. Incorporate the most relevant chunks into your answer, citing the source `title` from metadata

        Available collections: {col_list}
        To search a specific collection, set `"collection"` in the request body.
    """)

    upload_skill = textwrap.dedent(f"""\
        ---
        description: Upload a document or text to the knowledge base so it can be searched later.
        ---

        Upload content to the knowledge platform at {base_url}.

        **To add inline text**:
        ```bash
        curl -X POST {base_url}/me/documents/text \\
          -H "Content-Type: application/json" \\
          -H "Authorization: Bearer <token>" \\
          -d '{{"title": "My Note", "content": "...", "collection": "default"}}'
        ```

        After upload you'll receive a `doc_id` — save it to delete the document later.

        **To delete a document**:
        ```bash
        curl -X DELETE "{base_url}/me/documents/{{doc_id}}?collection=default" \\
          -H "Authorization: Bearer <token>"
        ```
    """)

    return {
        "search-knowledge": search_skill,
        "upload-document": upload_skill,
    }


# ── Hermes (NousResearch function-calling format) ────────────────────────────

@router.get("/hermes")
async def get_hermes_config(request: Request):
    """
    Export tool definitions in NousResearch Hermes function-calling format.

    The Hermes format uses ChatML with tool definitions placed in the system prompt.
    Compatible with: Hermes-2-Pro-*, Hermes-3-*, and any Hermes-fine-tuned model.
    """
    base_url = str(request.base_url).rstrip("/")
    tools = _tool_schemas(base_url)

    system_prompt = textwrap.dedent("""\
        You are a helpful AI assistant with access to a personal knowledge base.
        You have the following tools available. Use them whenever a question requires
        domain-specific knowledge from uploaded documents.

        When using a tool, respond ONLY with:
        <tool_call>
        {"name": "<tool_name>", "arguments": {<args as JSON>}}
        </tool_call>

        After receiving a tool result (wrapped in <tool_response>), incorporate
        the information into your final answer.
    """)

    return {
        "framework": "hermes",
        "format": "chatml",
        "compatible_models": [
            "NousResearch/Hermes-2-Pro-Mistral-7B",
            "NousResearch/Hermes-2-Pro-Llama-3-8B",
            "NousResearch/Hermes-3-Llama-3.1-8B",
        ],
        "system_prompt": system_prompt,
        "tools": tools,
        "api": _api_impl_block(base_url),
        "example_chatml": _hermes_example_chatml(base_url),
    }


def _hermes_example_chatml(base_url: str) -> str:
    return textwrap.dedent(f"""\
        <|im_start|>system
        You are a helpful AI assistant with access to a personal knowledge base.
        You have the following tools available:

        {json.dumps(_tool_schemas(base_url), ensure_ascii=False, indent=2)}

        When using a tool, respond ONLY with:
        <tool_call>
        {{"name": "<tool_name>", "arguments": {{<args>}}}}
        </tool_call>
        <|im_end|>
        <|im_start|>user
        帮我查一下关于产品规划的内容
        <|im_end|>
        <|im_start|>assistant
        <tool_call>
        {{"name": "search_knowledge", "arguments": {{"query": "产品规划", "top_k": 5}}}}
        </tool_call>
        <|im_end|>
        <|im_start|>tool
        <tool_response>
        {{"results": [{{"rank": 1, "score": 0.87, "title": "2024 Q4 产品规划", "content": "..."}}]}}
        </tool_response>
        <|im_end|>
        <|im_start|>assistant
        根据知识库中的文档《2024 Q4 产品规划》，...
        <|im_end|>""")


# ── OpenLCAW / OpenAI-compatible function calling ────────────────────────────

@router.get("/openlcaw")
async def get_openlcaw_config(request: Request):
    """
    Export tool definitions in OpenAI-compatible function calling format.

    Compatible with any framework that implements the OpenAI tools API:
    LangChain, LlamaIndex, AutoGen, CrewAI, Dify, FastGPT, OpenLCAW, etc.
    """
    base_url = str(request.base_url).rstrip("/")
    tools = _tool_schemas(base_url)

    python_snippet = textwrap.dedent(f"""\
        import requests

        BASE_URL = "{base_url}"

        # 1. Get token
        token_resp = requests.post(f"{{BASE_URL}}/auth/token",
            json={{"username": "YOUR_USERNAME", "password": "YOUR_PASSWORD"}})
        token = token_resp.json()["access_token"]
        headers = {{"Authorization": f"Bearer {{token}}", "Content-Type": "application/json"}}

        # 2. Search the knowledge base
        def search_knowledge(query: str, collection: str = "default", top_k: int = 5):
            resp = requests.post(f"{{BASE_URL}}/me/search",
                headers=headers,
                json={{"query": query, "collection": collection, "top_k": top_k}})
            return resp.json()

        # 3. Use with OpenAI-compatible client (e.g. LangChain, AutoGen)
        # Pass `tools` below to your LLM's tool_choice parameter
    """)

    langchain_snippet = textwrap.dedent(f"""\
        from langchain.tools import StructuredTool
        import requests

        BASE = "{base_url}"
        TOKEN = "YOUR_BEARER_TOKEN"  # from POST {base_url}/auth/token
        HEADERS = {{"Authorization": f"Bearer {{TOKEN}}"}}

        def search_knowledge(query: str, collection: str = "default", top_k: int = 5) -> dict:
            return requests.post(f"{{BASE}}/me/search", headers=HEADERS,
                json={{"query": query, "collection": collection, "top_k": top_k}}).json()

        def list_collections() -> dict:
            return requests.get(f"{{BASE}}/me/collections", headers=HEADERS).json()

        def add_text_document(title: str, content: str, collection: str = "default") -> dict:
            return requests.post(f"{{BASE}}/me/documents/text", headers=HEADERS,
                json={{"title": title, "content": content, "collection": collection}}).json()

        # Register as LangChain tools
        tools = [
            StructuredTool.from_function(search_knowledge),
            StructuredTool.from_function(list_collections),
            StructuredTool.from_function(add_text_document),
        ]
    """)

    return {
        "framework": "openai-compatible",
        "compatible_with": [
            "OpenLCAW", "LangChain", "LlamaIndex", "AutoGen",
            "CrewAI", "Dify", "FastGPT", "OpenAI Assistants API",
        ],
        "tools": tools,
        "api": _api_impl_block(base_url),
        "code_snippets": {
            "python_requests": python_snippet,
            "langchain": langchain_snippet,
        },
    }
