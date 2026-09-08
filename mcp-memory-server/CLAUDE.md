# MCP Memory Server

PostgreSQL + FastMCP 实现的项目记忆存储服务。

## 工具

| 工具 | 用途 |
|------|------|
| `save_memory` | 保存记忆（相同标题自动更新） |
| `search_memory` | 按关键词/模块/类型搜索记忆 |
| `get_module_context` | 加载模块或项目级全部记忆 |
| `get_memory_titles` | 获取记忆标题列表（轻量） |
| `count_memories` | 统计记忆数量 |
| `update_memory` | 更新已有记忆（旧版本自动存档） |
| `delete_memory` | 删除记忆（删除前存档最终版本） |
| `delete_project` | 级联删除项目及其所有记忆（需复述项目名确认，删除前全量存档） |
| `list_projects` | 列出所有项目 |

## 记忆类型

- `decision` — 技术选型、架构决策
- `progress` — 模块开发进展
- `pitfall` — 踩坑记录、已知问题
- `architecture` — 系统架构、模块关系
- `convention` — 团队约定、编码规范

## 启动

```bash
# Docker Compose（一键启动）
docker-compose up -d

# 或手动
pip install -r requirements.txt
python server.py
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | 必须 | PostgreSQL 连接字符串 |
| `MCP_HOST` | `0.0.0.0` | 服务监听地址 |
| `MCP_PORT` | `8100` | 服务监听端口 |
| `MCP_DNS_REBINDING_PROTECTION` | `true` | DNS rebinding 防护，生产环境不要关闭 |