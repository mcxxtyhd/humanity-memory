# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Humanity Memory — 跨会话、跨工程师的项目记忆管理系统。通过 MCP 协议与 Claude Code 集成，AI 在多次对话中自动采集、召回、整理项目记忆。

## 核心组件

- `humanity-memory.md` — Skill 文件（用户通过 `/humanity-memory` 命令调用）
- `mcp-memory-server/` — MCP Server 实现（Python FastMCP + PostgreSQL）

## 开发命令

```bash
# 启动服务（Docker Compose）
cd mcp-memory-server
docker-compose up -d

# 本地运行（需先启动 PostgreSQL）
pip install -r requirements.txt
python server.py

# 运行测试
pytest
```

## 架构

```
Claude Code → humanity-memory skill → MCP Protocol → memory-server (FastMCP HTTP) → PostgreSQL
```

MCP Server 基于 FastMCP，运行在 8100 端口，提供 `save_memory`、`search_memory`、`get_module_context` 等工具。数据库使用 PostgreSQL，通过 trigram 索引支持中文全文搜索。

## 目录结构

```
mcp-memory-server/
├── server.py         # FastMCP HTTP 服务入口
├── db.py             # 数据库操作（psycopg_pool 异步连接池）
├── schema.sql        # PostgreSQL schema（含迁移）
├── requirements.txt  # Python 依赖
└── docker-compose.yml
```

## Memory

- project_id: humanity-memory