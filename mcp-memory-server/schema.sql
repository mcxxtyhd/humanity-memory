-- Enable trigram extension for Chinese text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id          VARCHAR(50) PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Memories table
CREATE TABLE IF NOT EXISTS memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  VARCHAR(50) NOT NULL REFERENCES projects(id),
    module      VARCHAR(100),
    type        VARCHAR(20) NOT NULL CHECK (type IN ('decision', 'progress', 'pitfall', 'architecture', 'convention')),
    title       VARCHAR(300) NOT NULL,
    content     TEXT NOT NULL,
    tags        TEXT[] DEFAULT '{}',
    author      VARCHAR(50) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Trigram indexes for Chinese text search
CREATE INDEX IF NOT EXISTS idx_memories_title_trgm ON memories USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_content_trgm ON memories USING GIN (content gin_trgm_ops);
-- Query indexes
CREATE INDEX IF NOT EXISTS idx_memories_project_module ON memories(project_id, module);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING GIN(tags);

-- Memory versions table (no FK — survives parent deletion for audit)
CREATE TABLE IF NOT EXISTS memory_versions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id   UUID NOT NULL,
    title       VARCHAR(300) NOT NULL,
    content     TEXT NOT NULL,
    author      VARCHAR(50) NOT NULL,
    changed_at  TIMESTAMPTZ DEFAULT now(),
    change_note VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS idx_memory_versions_memory_id ON memory_versions(memory_id);

-- Migration: add access tracking fields (safe to re-run)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='access_count') THEN
        ALTER TABLE memories ADD COLUMN access_count INTEGER DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='last_accessed_at') THEN
        ALTER TABLE memories ADD COLUMN last_accessed_at TIMESTAMPTZ;
    END IF;
END $$;
