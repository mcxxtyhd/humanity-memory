# MCP Memory Server 使用指南

## 团队共享记忆

本项目配置了远程 MCP Memory Server，用于团队共享项目记忆。所有工程师的 Claude 会话共享同一个记忆库。

## 可用工具

| 工具 | 用途 |
|------|------|
| `save_memory` | 保存记忆（相同标题自动更新） |
| `search_memory` | 按关键词/模块/类型搜索记忆 |
| `get_module_context` | 加载模块或项目级全部记忆（新会话启动时调用） |
| `update_memory` | 更新已有记忆 |
| `delete_memory` | 删除记忆 |
| `list_projects` | 列出所有项目 |

## 记忆类型

- `decision` — 技术选型、架构决策（细粒度）
- `progress` — 模块开发进展（粗粒度）
- `pitfall` — 踩坑记录、已知问题（细粒度）
- `architecture` — 系统架构、模块关系（粗粒度）
- `convention` — 团队约定、编码规范（细粒度）

## 使用约定

- `author` 使用当前 git user.name
- 新会话开始时，调用 `get_module_context` 加载当前工作模块的上下文
- 工作过程中遇到以下情况时自动调用 `save_memory`：
  - 做出了技术选型或架构决策
  - 踩了坑并找到了解决方案
  - 模块开发阶段有重要进展
  - 确立了新的团队约定或编码规范
- 不要保存：临时调试信息、个人偏好、代码片段、可从 git 历史推导的信息
