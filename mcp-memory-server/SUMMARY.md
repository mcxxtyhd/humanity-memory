# Humanity Memory — 团队共享 AI 记忆系统

## 这是什么

一套为多人 vibecoding 场景设计的 AI 记忆系统。核心解决的问题：每个工程师开新的 Claude Code 会话时，AI 都是"失忆"的。这套系统让所有工程师的 Claude 会话共享同一个记忆库，新会话启动时自动加载项目上下文。

组成部分：
- **MCP Memory Server**：Python 服务，连接 PostgreSQL，暴露记忆 CRUD 工具
- **humanity-memory Skill**：Claude Code 的 slash command，定义记忆的采集、召回、整理策略

## 技术选型与决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 数据库 | PostgreSQL 16 | 多客户端并发连接，团队共享场景。SQLite 是单文件不支持网络访问 |
| MCP 传输 | Streamable HTTP | MCP 官方推荐的远程传输方式，SSE 已废弃 |
| 开发语言 | Python | Anthropic 官方 MCP SDK 支持好 |
| 中文搜索 | pg_trgm 三元组索引 | PostgreSQL 内置 tsvector 不支持中文分词，pg_trgm 无需额外插件 |
| 部署方式 | PG 用 Docker，MCP Server 也用 Docker（同一个 docker-compose） | 离线机器无法 pip install，Docker 镜像打包所有依赖 |
| 记忆粒度 | 混合 | 重要决策细粒度单独记录，模块进展粗粒度聚合 |
| 记忆范围 | 仅项目记忆 | 个人偏好仍用本地 .claude/memory/，共享库只存项目相关 |

## 数据模型

三张表：

**projects** — 项目注册
- id (VARCHAR PK)、name、description、created_at

**memories** — 记忆主表
- id (UUID PK)、project_id (FK)、module、type、title、content、tags[]、author
- access_count、last_accessed_at — 访问追踪，用于睡眠整理时判断记忆价值
- created_at、updated_at

**memory_versions** — 版本历史（无外键，删除记忆后保留审计）
- id、memory_id、title、content、author、changed_at、change_note

记忆类型：decision / progress / pitfall / architecture / convention

去重机制：project_id + module + type + title（title 规范化后精确匹配）

## MCP 工具接口（13 个）

| 工具 | 用途 |
|------|------|
| save_memory | 保存记忆，相同标题自动 upsert |
| search_memory | 按关键词/模块/类型搜索，支持中文 |
| get_module_context | 加载全量记忆（含全文），按 type 分组 |
| get_memory_titles | 会话启动索引：id/module/title/tags（轻量，无正文/摘要/type），按更新时间倒序 |
| get_memory_index | 轻量索引 + 结构化摘要，支持 module/type/tags 过滤 |
| get_memory | 按 id 取单条全文 |
| get_memories | 按 id 批量取全文 |
| count_memories | 统计记忆数量，按 type 分组 |
| update_memory | 更新记忆，自动存版本历史 |
| delete_memory | 删除记忆，删前存最终版本快照 |
| delete_project | 级联删除项目及其记忆（需复述项目名确认，删前全量存档） |
| list_projects | 列出所有项目 |
| get_project | 按 id 查项目 |

## Skill 设计（humanity-memory）

四个阶段：

### 阶段一：项目识别
CLAUDE.md 有 project_id → 直接用 → 没有 → list_projects 匹配 → 匹配不到 → 引导创建 → 回写 CLAUDE.md（只需交互一次）

### 阶段二：记忆召回
- ≤ 30 条：get_module_context 加载全文，跳过索引
- \> 30 条：get_memory_titles 加载轻量索引（id/module/title/tags，按更新时间倒序），按需读全文
- 扫描 shared- 项目备用，不立即加载
- 记忆 > 100 条时提醒用户整理

### 阶段三：记忆采集（行为规则，贯穿会话）
- 自动采集：低门槛，技术决策/踩坑/进展/架构/约定都存
- 手动触发：用户说"记住这个"
- 跨项目经验自动存到 shared- 项目

### 阶段四：睡眠整理（按需触发）
- 合并相似记忆、淘汰过时记忆、提炼总结、解决矛盾
- 参考 access_count 和 last_accessed_at 判断记忆价值

## Shared 项目机制

以 `shared-` 开头的特殊项目，存放跨项目通用知识：
- shared-pitfalls — 通用踩坑集
- shared-sql-mastery — SQL 处理经验
- shared-vue-patterns — Vue3 开发模式
- 等等，按需创建

每个 shared 项目有 description 描述其领域。CC 根据描述判断何时搜索哪个 shared 项目。

## 部署架构

```
工程师 A 的 Claude Code ──┐
工程师 B 的 Claude Code ──┼── HTTP ──→ MCP Memory Server ──→ PostgreSQL
工程师 C 的 Claude Code ──┘           (Docker 容器)          (Docker 容器)
                                      端口 8100              端口 8998(外)/5432(内)
```

docker-compose.yml 管理两个容器，同一网络内通过服务名通信。

## 客户端配置

```bash
# 添加 MCP Server（所有项目可用）
claude mcp add --transport http --scope user theo-memory http://<linux-ip>:8100/mcp
```

Skill 放在 `~/.claude/commands/humanity-memory.md`，所有项目可用。

## 踩过的坑

1. **DNS rebinding 保护**：MCP SDK 默认只允许 localhost 的 Host header，外部 IP 访问返回 421。解决：`TransportSecuritySettings(enable_dns_rebinding_protection=False)`

2. **schema migration 死锁**：`stateless_http=True` 模式下每个请求触发 lifespan，并发执行 ALTER TABLE 导致死锁。解决：加 `_initialized` 标志确保只执行一次

3. **SQL split 切碎 DO $$ 块**：用 `split(";")` 逐语句执行 schema.sql 时，会把 `DO $$ BEGIN ... END $$;` 内部的分号也切开。解决：直接 `conn.execute(schema_sql)` 执行整个文件

4. **psycopg tsvector 不支持中文**：PostgreSQL 的 `to_tsvector('simple', ...)` 按空格分词，对中文无效。解决：用 pg_trgm 扩展 + ILIKE 搜索

5. **memory_versions CASCADE 删除**：外键设 ON DELETE CASCADE 会导致删记忆时版本历史也被删，"版本兜底"失效。解决：去掉外键约束，保留 memory_id 值用于审计

6. **CentOS 7 无外网无 Python 3**：目标机器 Python 2.7 且无法 pip install。解决：本地 Docker build 打包所有依赖，导出 tar 传到机器 docker load

7. **MCP_ALLOWED_HOSTS 不存在**：网上有人说设这个环境变量可以解决 Host header 校验，但 SDK 源码里根本不读任何环境变量。必须通过代码配置 TransportSecuritySettings

## 项目文件清单

```
mcp-memory-server/
├── server.py          # FastMCP 服务，8 个工具定义
├── db.py              # 异步连接池 + 所有 SQL 操作
├── schema.sql         # 建表 DDL + migration
├── requirements.txt   # Python 依赖
├── .env.example       # 配置模板
├── Dockerfile         # 构建镜像用
└── CLAUDE.md          # MCP 使用指南（参考文档）

~/.claude/commands/
└── humanity-memory.md # 全局 Skill
```

## 调研过的开源方案

| 项目 | Stars | 特点 | 不足 |
|------|-------|------|------|
| Engram | 2.5k | 最成熟，单二进制，git sync | 不是实时共享，是文件同步 |
| Nocturne Memory | 961 | 版本控制最强，有 Dashboard | 设计初衷是 AI 人格记忆 |
| Eion | 149 | 原生多 Agent 共享 | 架构重（PG+Neo4j），不成熟 |
| Context Portal | 761 | 项目知识图谱 | 单人本地，无团队共享 |

没有一个完美匹配"团队共享 + 版本管理 + 项目工程记忆 + MCP 集成"的需求，所以自建。
