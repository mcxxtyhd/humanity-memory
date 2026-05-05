# Humanity Memory

跨会话、跨工程师的项目记忆管理系统。模拟人类记忆机制，让 AI 在多次对话中保持对项目的持续理解。

## 特性

- **自动记忆采集** — 技术选型、踩坑记录、模块进展自动保存
- **版本历史** — 所有变更完整保留，可追溯
- **中文全文搜索** — PostgreSQL trigram 索引，模糊匹配
- **MCP 协议** — 原生接入 Claude Code，无需额外配置

## 架构

```
┌─────────────────────────────────────────────────────┐
│                    Claude Code                      │
│                                                      │
│   humanity-memory skill ←─────── MCP 协议            │
└─────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────┐
│              MCP Memory Server (HTTP)                │
│                     port 8100                        │
└─────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────┐
│                    PostgreSQL                       │
│                  (记忆持久化存储)                     │
└─────────────────────────────────────────────────────┘
```

## 快速启动

### 1. 启动服务（Docker Compose）

```bash
git clone https://github.com/anthropics/humanity-memory.git
cd humanity-memory/mcp-memory-server

# 可选：自定义密码
cp .env.example .env
# 编辑 .env 修改 POSTGRES_PASSWORD

# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f memory-server
```

### 2. 配置 Claude Code

部署服务后，用 `mcp add` 命令添加 MCP server：

```bash
# 添加本地服务
claude mcp add humanity-memory --transport http http://localhost:8100

# 或添加远程服务器（将 IP 换成你的服务器地址）
claude mcp add humanity-memory --transport http http://你的服务器IP:8100
```

添加完成后，Claude Code 会自动连接。

### 3. 使用

在 Claude Code 中输入 `/humanity-memory` 即可激活记忆系统。

## 目录结构

```
humanity-memory/
├── humanity-memory.md    # Skill 文件（使用文档）
├── CLAUDE.md             # 项目说明
├── mcp-memory-server/    # MCP Server 实现
│   ├── server.py         # FastMCP HTTP 服务
│   ├── db.py             # 数据库操作
│   ├── schema.sql        # PostgreSQL schema
│   ├── requirements.txt  # Python 依赖
│   ├── Dockerfile        # 容器镜像
│   └── docker-compose.yml # 一键部署
```

## 记忆类型

| 类型 | 用途 | 示例 |
|------|------|------|
| `decision` | 技术选型、架构决策 | "后端用 MyBatis-Plus 不用 JPA" |
| `progress` | 模块开发进展 | "用户认证模块已完成" |
| `pitfall` | 踩坑记录、已知问题 | "LocalDateTime 序列化需要配置 Jackson" |
| `architecture` | 系统架构、模块关系 | "用户服务和权限服务合并为一个微服务" |
| `convention` | 团队约定、编码规范 | "所有 API 响应统一用 R<T> 包装" |

## 配置 Skill

### 方式一：用户级（推荐）

将 skill 文件复制到 Claude Code 用户配置目录：

```bash
# Windows
copy humanity-memory.md %USERPROFILE%\.claude\skills\humanity-memory.md

# macOS/Linux
cp humanity-memory.md ~/.claude/skills/humanity-memory.md
```

### 方式二：项目级（团队共享）

将 `humanity-memory.md` 和 `CLAUDE.md` 一起放到项目根目录，Claude Code 会自动加载。

### 方式三：仓库分发

将 skill 文件放到仓库根目录，用户 clone 后 Claude Code 自动识别。

---

## 配置 MCP Server

使用 `mcp add` 命令添加 MCP server：

```bash
# 本地服务
claude mcp add humanity-memory --transport http http://localhost:8100

# 远程服务器
claude mcp add humanity-memory --transport http http://你的服务器IP:8100
```

查看已添加的 server：

```bash
claude mcp list
```

移除 server：

```bash
claude mcp remove humanity-memory
```

## License

MIT