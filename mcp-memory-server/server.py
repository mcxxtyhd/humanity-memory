import argparse
import json
import os
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import db

load_dotenv()


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize DB pool on startup. Pool persists across stateless requests."""
    await db.init_pool()
    yield


mcp = FastMCP(
    "Memory Server",
    stateless_http=True,
    json_response=True,
    lifespan=app_lifespan,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=os.environ.get("MCP_DNS_REBINDING_PROTECTION", "true").lower() == "true",
    ),
)


def _serialize(obj):
    """JSON-serialize helper for datetime and UUID."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "hex"):
        return str(obj)
    return obj


def _clean(data):
    """Recursively clean dicts/lists for JSON serialization."""
    if isinstance(data, dict):
        return {k: _clean(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_clean(item) for item in data]
    return _serialize(data)


@mcp.tool()
async def save_memory(
    project_id: str,
    type: str,
    title: str,
    content: str,
    author: str,
    module: Optional[str] = None,
    tags: Optional[list[str]] = None,
    project_name: Optional[str] = None,
) -> str:
    """Save a project memory. Auto-upserts if same project+module+type+title exists.

    Args:
        project_id: Project identifier (e.g. "cn-tongfu")
        type: Memory type — decision / progress / pitfall / architecture / convention
        title: Short title for the memory
        content: Full memory content
        author: Who is writing this memory
        module: Optional module name (e.g. "auth"), null for project-level
        tags: Optional tags for filtering
        project_name: Optional project name, used only when auto-creating project
    """
    result = await db.save_memory(
        project_id=project_id,
        type_=type,
        title=title,
        content=content,
        author=author,
        module=module,
        tags=tags,
        project_name=project_name,
    )
    return json.dumps(_clean(result), ensure_ascii=False)


@mcp.tool()
async def search_memory(
    project_id: str,
    query: Optional[str] = None,
    module: Optional[str] = None,
    type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    limit: int = 10,
) -> str:
    """Search project memories with keyword and filters, sorted by relevance when query is provided.

    Args:
        project_id: Project identifier
        query: Search keyword (Chinese supported via trigram fuzzy matching)
        module: Filter by module name
        type: Filter by memory type
        tags: Filter by tags (all must match)
        limit: Max results (default 10)
    """
    results = await db.search_memory(
        project_id=project_id,
        query=query,
        module=module,
        type_=type,
        tags=tags,
        limit=limit,
    )
    return json.dumps(_clean(results), ensure_ascii=False)


@mcp.tool()
async def get_module_context(
    project_id: str,
    module: Optional[str] = None,
    include_all: bool = False,
) -> str:
    """Load all memories for a module or project-level, grouped by type.
    Call this at session start to load working context.
    When module is omitted, include_all must be true to load ALL full memories.

    Args:
        project_id: Project identifier
        module: Module name. Omit for all project memories.
        include_all: Explicitly allow full-project content loading. Use only for memory cleanup/audit.
    """
    if module is None and not include_all:
        return json.dumps(
            {
                "error": "Full-project memory content loading requires include_all=true. "
                         "Use get_memory_index for startup context, then get_memory/get_memories for details."
            },
            ensure_ascii=False,
        )

    grouped = await db.get_module_context(
        project_id=project_id,
        module=module,
    )
    return json.dumps(_clean(grouped), ensure_ascii=False)


@mcp.tool()
async def count_memories(
    project_id: str,
) -> str:
    """Count memories for a project, grouped by type. Use this to check memory volume.

    Args:
        project_id: Project identifier
    """
    result = await db.count_memories(project_id=project_id)
    return json.dumps(_clean(result), ensure_ascii=False)


@mcp.tool()
async def get_memory_titles(
    project_id: str,
    module: Optional[str] = None,
) -> str:
    """Get lightweight memory list (titles only, no content).
    Use this instead of get_module_context when you only need an overview.

    Args:
        project_id: Project identifier
        module: Module name. Omit for all project memories.
    """
    results = await db.get_memory_titles(
        project_id=project_id,
        module=module,
    )
    return json.dumps(_clean(results), ensure_ascii=False)


@mcp.tool()
async def get_memory_index(
    project_id: str,
    module: Optional[str] = None,
    type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> str:
    """Get a lightweight full-project memory index without full content.

    Use this at session start so vague user references can be resolved against
    titles, modules, tags, dates, and short summaries before loading details.

    Args:
        project_id: Project identifier
        module: Optional module filter
        type: Optional memory type filter
        tags: Optional tags filter (all must match)
        limit: Optional max results. Omit to return the full lightweight index.
    """
    results = await db.get_memory_index(
        project_id=project_id,
        module=module,
        type_=type,
        tags=tags,
        limit=limit,
    )
    return json.dumps(_clean(results), ensure_ascii=False)


@mcp.tool()
async def get_memory(project_id: str, memory_id: str) -> str:
    """Get one full memory by id.

    Args:
        project_id: Project identifier
        memory_id: Memory UUID
    """
    memory = await db.get_memory(project_id=project_id, memory_id=memory_id)
    if memory is None:
        return json.dumps({"error": f"Memory {memory_id} not found in project {project_id}"}, ensure_ascii=False)
    return json.dumps(_clean(memory), ensure_ascii=False)


@mcp.tool()
async def get_memories(project_id: str, memory_ids: list[str]) -> str:
    """Get multiple full memories by id.

    Args:
        project_id: Project identifier
        memory_ids: Memory UUIDs
    """
    memories = await db.get_memories(project_id=project_id, memory_ids=memory_ids)
    return json.dumps(_clean(memories), ensure_ascii=False)


@mcp.tool()
async def update_memory(
    memory_id: str,
    author: str,
    content: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    change_note: Optional[str] = None,
) -> str:
    """Update an existing memory. Old version is saved automatically.

    Args:
        memory_id: UUID of the memory to update
        author: Who is making this change
        content: New content (optional)
        title: New title (optional)
        tags: New tags (optional)
        change_note: Reason for the change (optional)
    """
    result = await db.update_memory(
        memory_id=memory_id,
        author=author,
        content=content,
        title=title,
        tags=tags,
        change_note=change_note,
    )
    if result is None:
        return json.dumps({"error": f"Memory {memory_id} not found"})
    return json.dumps(_clean(result), ensure_ascii=False)


@mcp.tool()
async def delete_memory(
    memory_id: str,
    author: str,
) -> str:
    """Delete a memory. A final version snapshot is saved before deletion.

    Args:
        memory_id: UUID of the memory to delete
        author: Who is deleting this memory
    """
    deleted = await db.delete_memory(memory_id=memory_id, author=author)
    if not deleted:
        return json.dumps({"error": f"Memory {memory_id} not found"})
    return json.dumps({"status": "deleted", "memory_id": memory_id})


@mcp.tool()
async def list_projects() -> str:
    """List all registered projects."""
    projects = await db.list_projects()
    return json.dumps(_clean(projects), ensure_ascii=False)


@mcp.tool()
async def get_project(project_id: str) -> str:
    """Get one registered project by id.

    Args:
        project_id: Project identifier
    """
    project = await db.get_project(project_id=project_id)
    if project is None:
        return json.dumps({"error": f"Project {project_id} not found"}, ensure_ascii=False)
    return json.dumps(_clean(project), ensure_ascii=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP Memory Server")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8100")))
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport="streamable-http")
