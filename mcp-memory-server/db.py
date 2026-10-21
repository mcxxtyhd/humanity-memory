import os
import re
from contextlib import asynccontextmanager
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: Optional[AsyncConnectionPool] = None
_initialized: bool = False


async def init_pool():
    """Initialize the async connection pool and run schema migration (once only)."""
    global _pool, _initialized
    if _initialized:
        return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    _pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row},
    )
    await _pool.open()
    # Run schema on startup — use autocommit for CREATE EXTENSION
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    async with _pool.connection() as conn:
        await conn.set_autocommit(True)
        await conn.execute(schema_sql)
        await conn.set_autocommit(False)
    _initialized = True


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_conn():
    """Get a connection from the pool."""
    async with _pool.connection() as conn:
        yield conn


def _normalize_title(title: str) -> str:
    """Normalize title for dedup: strip whitespace and punctuation."""
    return re.sub(r"[\s\u3000:：\-—·.。、,，;；!！?？]+", "", title).lower()


def _extract_summary(content: Optional[str], max_len: int = 120) -> str:
    """Extract a one-line structural preview from markdown content.

    Replaces blind ``left(content, N)`` truncation, which grabbed the leading
    ``#`` heading (duplicating the title) and cut mid-sentence markdown. Here we
    skip headings and prefer the first blockquote line (conventionally the
    'why'/context in this project's memories), falling back to the first prose
    line. Capped at ``max_len``.
    """
    if not content:
        return ""
    summary = ""
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith(">"):
            s = s.lstrip(">").strip()
        if s:
            summary = s
            break
    summary = re.sub(r"^[-*+]\s+", "", summary)
    if len(summary) > max_len:
        summary = summary[:max_len].rstrip() + "..."
    return summary


# --- Project operations ---

async def ensure_project(project_id: str, project_name: Optional[str] = None):
    """Create project if it doesn't exist."""
    name = project_name or project_id
    async with get_conn() as conn:
        await conn.execute(
            """INSERT INTO projects (id, name) VALUES (%s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (project_id, name),
        )
        await conn.commit()


async def list_projects() -> list[dict]:
    """List all projects."""
    async with get_conn() as conn:
        cur = await conn.execute(
            "SELECT id, name, description, created_at FROM projects ORDER BY created_at"
        )
        return await cur.fetchall()


async def get_project(project_id: str) -> Optional[dict]:
    """Get one project by id."""
    async with get_conn() as conn:
        cur = await conn.execute(
            "SELECT id, name, description, created_at FROM projects WHERE id = %s",
            (project_id,),
        )
        return await cur.fetchone()


async def delete_project(
    project_id: str,
    author: str,
    confirm_name: Optional[str] = None,
) -> dict:
    """Delete a project and all its memories (cascade), after echo-name confirmation.

    Requires confirm_name to exactly match the project's name — the
    "echo the name to delete" guard against accidental deletion by AI callers.
    Every memory is snapshotted into memory_versions (change_note marks the
    project deletion) before removal, so the audit trail survives.

    Returns one of:
        {"status": "not_found"}
        {"status": "confirmation_required", "project": {...}, "memory_count": N}
        {"status": "deleted", "project_id": ..., "name": ..., "memories_deleted": N}
    """
    async with get_conn() as conn:
        cur = await conn.execute(
            "SELECT id, name FROM projects WHERE id = %s", (project_id,)
        )
        project = await cur.fetchone()
        if not project:
            return {"status": "not_found"}

        if confirm_name != project["name"]:
            cur = await conn.execute(
                "SELECT COUNT(*) AS count FROM memories WHERE project_id = %s",
                (project_id,),
            )
            count_row = await cur.fetchone()
            return {
                "status": "confirmation_required",
                "project": project,
                "memory_count": count_row["count"],
                "hint": 'Re-call with confirm_name="%s" to delete' % project["name"],
            }

        # Snapshot all memories for audit before deletion (no FK by design)
        await conn.execute(
            """INSERT INTO memory_versions (memory_id, title, content, author, change_note)
               SELECT id, title, content, %s, %s FROM memories WHERE project_id = %s""",
            (author, "project deleted: %s" % project_id, project_id),
        )
        cur = await conn.execute(
            "DELETE FROM memories WHERE project_id = %s", (project_id,)
        )
        memories_deleted = cur.rowcount
        await conn.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        await conn.commit()
        return {
            "status": "deleted",
            "project_id": project_id,
            "name": project["name"],
            "memories_deleted": memories_deleted,
        }


# --- Memory operations ---

async def save_memory(
    project_id: str,
    type_: str,
    title: str,
    content: str,
    author: str,
    module: Optional[str] = None,
    tags: Optional[list[str]] = None,
    project_name: Optional[str] = None,
) -> dict:
    """Save or upsert a memory. Returns {"id": uuid, "action": "created"|"updated"}."""
    await ensure_project(project_id, project_name)
    normalized = _normalize_title(title)
    tags = tags or []

    async with get_conn() as conn:
        # Check for existing memory with same dedup key
        cur = await conn.execute(
            """SELECT id, title, content FROM memories
               WHERE project_id = %s
                 AND COALESCE(module, '') = COALESCE(%s, '')
                 AND type = %s""",
            (project_id, module, type_),
        )
        rows = await cur.fetchall()
        existing = None
        for row in rows:
            if _normalize_title(row["title"]) == normalized:
                existing = row
                break

        if existing:
            # Upsert: save old version, then update
            await conn.execute(
                """INSERT INTO memory_versions (memory_id, title, content, author, change_note)
                   VALUES (%s, %s, %s, %s, %s)""",
                (existing["id"], existing["title"], existing["content"], author, "auto-upsert via save_memory"),
            )
            await conn.execute(
                """UPDATE memories SET title = %s, content = %s, tags = %s,
                          author = %s, updated_at = now()
                   WHERE id = %s""",
                (title, content, tags, author, existing["id"]),
            )
            await conn.commit()
            return {"id": str(existing["id"]), "action": "updated"}
        else:
            # Insert new
            cur = await conn.execute(
                """INSERT INTO memories (project_id, module, type, title, content, tags, author)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (project_id, module, type_, title, content, tags, author),
            )
            row = await cur.fetchone()
            await conn.commit()
            return {"id": str(row["id"]), "action": "created"}


async def search_memory(
    project_id: str,
    query: Optional[str] = None,
    module: Optional[str] = None,
    type_: Optional[str] = None,
    tags: Optional[list[str]] = None,
    limit: int = 10,
) -> list[dict]:
    """Search memories with optional filters.

    Uses pg_trgm similarity for fuzzy matching and relevance sorting when a
    query is provided, while keeping ILIKE so exact substring matches stay fast
    and predictable for short Chinese queries.
    """
    conditions = ["project_id = %s"]
    filter_params: list = [project_id]
    rank_params: list = []

    if module is not None:
        conditions.append("module = %s")
        filter_params.append(module)
    if type_ is not None:
        conditions.append("type = %s")
        filter_params.append(type_)
    if tags:
        conditions.append("tags @> %s")
        filter_params.append(tags)
    if query:
        terms = [term for term in re.split(r"\s+", query.strip()) if term]
        term_conditions = []
        rank_parts = []
        for term in terms:
            like_pattern = f"%{term}%"
            term_conditions.append(
                "(title ILIKE %s OR content ILIKE %s "
                "OR title %% %s "
                "OR content %% %s)"
            )
            filter_params.extend([
                like_pattern,
                like_pattern,
                term,
                term,
            ])
            rank_parts.append(
                "GREATEST(similarity(title, %s) * 2.0, similarity(content, %s))"
            )
            rank_params.extend([term, term])
        if term_conditions:
            conditions.append(f"({' OR '.join(term_conditions)})")
            relevance_sql = " + ".join(rank_parts)
            order_sql = "relevance_score DESC, updated_at DESC"
        else:
            relevance_sql = "0.0"
            order_sql = "updated_at DESC"
    else:
        relevance_sql = "0.0"
        order_sql = "updated_at DESC"

    where = " AND ".join(conditions)
    params = rank_params + filter_params + [limit]

    async with get_conn() as conn:
        cur = await conn.execute(
            f"""SELECT id, project_id, module, type, title, content, tags, author,
                       created_at, updated_at, access_count, last_accessed_at,
                       {relevance_sql} AS relevance_score
                FROM memories WHERE {where}
                ORDER BY {order_sql} LIMIT %s""",
            params,
        )
        rows = await cur.fetchall()
        # Update access tracking
        if rows:
            ids = [row["id"] for row in rows]
            await conn.execute(
                """UPDATE memories SET access_count = access_count + 1,
                          last_accessed_at = now()
                   WHERE id = ANY(%s)""",
                (ids,),
            )
            await conn.commit()
        return rows


async def get_memory_index(
    project_id: str,
    module: Optional[str] = None,
    type_: Optional[str] = None,
    tags: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Get a lightweight memory index without full content.

    Returns only id/module/type/title/tags/created_at plus a short structural
    `summary` (first blockquote or first prose line, ~120 chars) extracted from
    content -- NOT a blind left(content,N) truncation, which duplicated the
    title heading and cut mid-sentence markdown. Redundant fields (project_id,
    author, updated_at, access_count, last_accessed_at) are omitted to keep the
    payload small; full metadata is available via get_memory/get_memories.
    """
    conditions = ["project_id = %s"]
    params: list = [project_id]

    if module is not None:
        conditions.append("module = %s")
        params.append(module)
    if type_ is not None:
        conditions.append("type = %s")
        params.append(type_)
    if tags:
        conditions.append("tags @> %s")
        params.append(tags)

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT %s"
        params.append(limit)

    where = " AND ".join(conditions)
    async with get_conn() as conn:
        cur = await conn.execute(
            f"""SELECT id, module, type, title, tags, created_at,
                       left(content, 800) AS _content_head
                FROM memories WHERE {where}
                ORDER BY updated_at DESC {limit_sql}""",
            params,
        )
        rows = await cur.fetchall()
    for row in rows:
        row["summary"] = _extract_summary(row.pop("_content_head", ""))
    return rows


async def get_memory(project_id: str, memory_id: str) -> Optional[dict]:
    """Get one full memory by id within a project."""
    async with get_conn() as conn:
        cur = await conn.execute(
            """SELECT id, project_id, module, type, title, content, tags, author,
                      created_at, updated_at, access_count, last_accessed_at
               FROM memories WHERE project_id = %s AND id = %s""",
            (project_id, memory_id),
        )
        row = await cur.fetchone()
        if row:
            await conn.execute(
                """UPDATE memories SET access_count = access_count + 1,
                          last_accessed_at = now()
                   WHERE id = %s""",
                (memory_id,),
            )
            await conn.commit()
        return row


async def get_memories(project_id: str, memory_ids: list[str]) -> list[dict]:
    """Get full memories by ids within a project."""
    if not memory_ids:
        return []

    async with get_conn() as conn:
        cur = await conn.execute(
            """SELECT id, project_id, module, type, title, content, tags, author,
                      created_at, updated_at, access_count, last_accessed_at
               FROM memories
               WHERE project_id = %s AND id = ANY(%s::uuid[])
               ORDER BY updated_at DESC""",
            (project_id, memory_ids),
        )
        rows = await cur.fetchall()
        if rows:
            ids = [row["id"] for row in rows]
            await conn.execute(
                """UPDATE memories SET access_count = access_count + 1,
                          last_accessed_at = now()
                   WHERE id = ANY(%s)""",
                (ids,),
            )
            await conn.commit()
        return rows


async def get_module_context(
    project_id: str,
    module: Optional[str] = None,
) -> dict[str, list[dict]]:
    """Load all memories for a project, optionally filtered by module, grouped by type.
    When module is omitted, returns ALL memories (project-level + all modules).
    When module is provided, returns only that module's memories."""
    if module is not None:
        condition = "project_id = %s AND module = %s"
        params = (project_id, module)
    else:
        condition = "project_id = %s"
        params = (project_id,)

    async with get_conn() as conn:
        cur = await conn.execute(
            f"""SELECT id, project_id, module, type, title, content, tags, author,
                       created_at, updated_at, access_count, last_accessed_at
                FROM memories WHERE {condition}
                ORDER BY type, updated_at DESC""",
            params,
        )
        rows = await cur.fetchall()
        # Update access tracking
        if rows:
            ids = [row["id"] for row in rows]
            await conn.execute(
                """UPDATE memories SET access_count = access_count + 1,
                          last_accessed_at = now()
                   WHERE id = ANY(%s)""",
                (ids,),
            )
            await conn.commit()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        t = row["type"]
        if t not in grouped:
            grouped[t] = []
        grouped[t].append(row)
    return grouped


async def count_memories(project_id: str) -> dict:
    """Count memories for a project, grouped by type."""
    async with get_conn() as conn:
        cur = await conn.execute(
            """SELECT type, COUNT(*) as count FROM memories
               WHERE project_id = %s GROUP BY type""",
            (project_id,),
        )
        rows = await cur.fetchall()
        cur2 = await conn.execute(
            "SELECT COUNT(*) as total FROM memories WHERE project_id = %s",
            (project_id,),
        )
        total_row = await cur2.fetchone()
    by_type = {row["type"]: row["count"] for row in rows}
    return {"total": total_row["total"], "by_type": by_type}


async def get_memory_titles(
    project_id: str,
    module: Optional[str] = None,
) -> list[dict]:
    """Get lightweight memory list for a project -- the session-start index.

    Projection is deliberately narrow: id, module, title, tags. Every field
    kept here is one the agent cannot reconstruct without it:

    - id: exact by-id lookup, the fallback when search misses
    - module: `module = %s` in search_memory is an EXACT match, so the exact
      module literal is only learnable from this index
    - tags: the `query` path searches title/content only -- the tags column is
      NEVER reached by keyword search, only by the exact `tags @> %s` filter.
      An agent can only use that filter if it has seen the literal here.
    - title: the human-readable identity of the row

    Deliberately excluded: type (DB-constrained to 5 values that the skill
    file already documents, so the agent knows the literals without the
    index), author / created_at / updated_at / access_count /
    last_accessed_at (pure time+behaviour metadata -- none of them takes
    part in a recall decision; access_count additionally measures "was
    returned by a search", not "was useful").

    Ordered by updated_at DESC so the newest memory is first. Ordering by
    type used to bury a fresh pitfall behind every architecture/convention/
    decision row, and became an unlabeled grouping once type was dropped
    from the projection.
    """
    if module is not None:
        condition = "project_id = %s AND module = %s"
        params = (project_id, module)
    else:
        condition = "project_id = %s"
        params = (project_id,)

    async with get_conn() as conn:
        cur = await conn.execute(
            f"""SELECT id, module, title, tags
                FROM memories WHERE {condition}
                ORDER BY updated_at DESC""",
            params,
        )
        return await cur.fetchall()


async def update_memory(
    memory_id: str,
    author: str,
    content: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    change_note: Optional[str] = None,
) -> Optional[dict]:
    """Update a memory, saving old version first. Returns updated memory or None."""
    async with get_conn() as conn:
        cur = await conn.execute(
            "SELECT * FROM memories WHERE id = %s", (memory_id,)
        )
        existing = await cur.fetchone()
        if not existing:
            return None

        # Save old version
        await conn.execute(
            """INSERT INTO memory_versions (memory_id, title, content, author, change_note)
               VALUES (%s, %s, %s, %s, %s)""",
            (memory_id, existing["title"], existing["content"], author, change_note),
        )

        # Build update
        sets = ["updated_at = now()"]
        params: list = []
        if content is not None:
            sets.append("content = %s")
            params.append(content)
        if title is not None:
            sets.append("title = %s")
            params.append(title)
        if tags is not None:
            sets.append("tags = %s")
            params.append(tags)
        sets.append("author = %s")
        params.append(author)
        params.append(memory_id)

        cur = await conn.execute(
            f"""UPDATE memories SET {', '.join(sets)} WHERE id = %s
                RETURNING id, project_id, module, type, title, content, tags, author, created_at, updated_at, access_count, last_accessed_at""",
            params,
        )
        result = await cur.fetchone()
        await conn.commit()
        return result


async def delete_memory(memory_id: str, author: str) -> bool:
    """Delete a memory. Returns True if deleted, False if not found."""
    async with get_conn() as conn:
        # Save final version before deletion
        cur = await conn.execute(
            "SELECT title, content FROM memories WHERE id = %s", (memory_id,)
        )
        existing = await cur.fetchone()
        if not existing:
            return False

        await conn.execute(
            """INSERT INTO memory_versions (memory_id, title, content, author, change_note)
               VALUES (%s, %s, %s, %s, %s)""",
            (memory_id, existing["title"], existing["content"], author, "deleted"),
        )
        await conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
        await conn.commit()
        return True
