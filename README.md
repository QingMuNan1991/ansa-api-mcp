# ANSA API MCP Server

基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 的 ANSA Python API 智能搜索服务。让 Claude Code / CodeBuddy 能够直接搜索和理解 ANSA API 文档，辅助用户编写 ANSA 脚本。

## 项目介绍

特别说明，本项目思路来自github账号RuFengLai：https://github.com/RufengLai/ansa-api-mcp.git，由本人基于ansa25.1.4的api，通过vibecoding进行了优化。

ANSA 是业界广泛使用的 CAE 前处理软件，其 Python API 包含 **5892 个函数**，分布在 **26 个模块**（基于 **ANSA v25.1.4** 的真实接口）中。面对如此庞大的 API 体系，开发者往往难以快速找到所需的函数。

本项目将 ANSA API 文档构建为结构化索引，并通过 MCP 协议暴露给客户端，使 AI 能够：

- 理解用户的自然语言意图（中英文均可）
- 精准定位对应的 ANSA API 函数
- 返回函数签名、参数说明和代码示例

### 覆盖的模块（26 个，v25.1.4）

| 模块 | 说明 |
|------|------|
| `ansa` | 顶层命名空间（主要为常量与通用入口） |
| `ansa.base` | 基础操作（查询、创建、修改、删除实体） |
| `ansa.base.checks.general` | 通用质量检查 |
| `ansa.base.checks.geometry` | 几何质量检查 |
| `ansa.base.checks.mesh` | 网格质量检查 |
| `ansa.base.checks.penetration` | 穿透检查 |
| `ansa.mesh` | 网格操作（划分、质量检查、编辑） |
| `ansa.morph` | 形状变形（映射、变形控制、DFM） |
| `ansa.connections` | 连接管理（焊点、螺栓等） |
| `ansa.dm` | 数据管理 |
| `ansa.calc` | 计算工具 |
| `ansa.kinetics` | 运动学分析 |
| `ansa.batchmesh` | 批量网格处理 |
| `ansa.report` | 报告生成 |
| `ansa.cad` | CAD 导入导出 |
| `ansa.analysis_tools` | 求解器/分析工具（如 RunSolver） |
| `ansa.constants` | 求解器与常量枚举（如 NASTRAN） |
| `ansa.sph` | SPH 求解相关 |
| `ansa.spdrm` / `ansa.spdrm.process` | 流程/任务编排 |
| `ansa.vr` | 虚拟现实交互 |
| `ansa.betascript` | Beta 脚本工具 |
| `ansa.session` | 会话/界面控制 |
| `ansa.taskmanager` | 任务管理 |
| `ansa.utils` | 通用工具函数 |
| `ansa.guitk` | GUI 工具包（自定义窗口/对话框、控件与对齐常量，含 340 个 `constants.*` 枚举） |

> 注：旧版索引基于 v24.1.1（2379 函数）；本版本已合并 v25.1.4 的真实接口（pydev 自动补全桩 + 旧索引的富文档/AI 关键词）升级而来。`ansa.guitk`（GUI 工具包，1190 个控件函数 + 340 个对齐/样式常量）此前因常量嵌套在 `class constants:` 内被解析器漏抓，现已修复并纳入。

## 功能特性

### 三层搜索策略

```
用户查询 → Layer 1: 关键词匹配
              ↓ (结果不足)
         Layer 2: 模糊子串搜索
              ↓ (结果不足)
         Layer 3: TXT 文档全文兜底
```

1. **关键词匹配** — 基于预生成的中英文关键词索引，精确匹配最相关的函数
2. **模糊搜索** — 在函数签名和描述中进行子串匹配，补充关键词未覆盖的结果
3. **TXT 文档兜底** — 在完整的 API 文档全文中搜索，确保不遗漏

### 中英文双语支持

内置中英文关键词映射，支持用中文描述需求：

```
用户: "删除实体"  →  ansa.base.DeleteEntity
用户: "delete entity" →  ansa.base.DeleteEntity
```

### 智能结果排序

- 关键词命中数越多，排名越靠前；命中的模块名/函数名有额外加权
- 返回函数签名、模块、分类、参数列表和代码示例
- 支持按 `module` 和 `category` 过滤

## 安装教程

### 前置条件

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 或兼容 MCP 的客户端

### 第一步：安装 MCP Server

**方式 A：有 Git 环境**

```bash
pip install git+https://github.com/RufengLai/ansa-api-mcp.git
```

**方式 B：没有 Git 环境**

```powershell
# 下载 zip
Invoke-WebRequest -Uri "https://codeload.github.com/RufengLai/ansa-api-mcp/zip/refs/heads/master" -OutFile "$env:TEMP\ansa-api-mcp.zip"
Expand-Archive -Path "$env:TEMP\ansa-api-mcp.zip" -DestinationPath "$env:TEMP" -Force

# 安装
cd "$env:TEMP\ansa-api-mcp-master"
pip install -e .
```

### 第二步：注册到 Claude Code

```bash
ansa-api-mcp install
```

输出示例：

```
Successfully registered ansa-api MCP server in Claude Code!
  Config: C:\Users\XXX\.claude.json
  Command: C:\...\Scripts\ansa-api-mcp.EXE

Restart Claude Code to start using it.
```

### 第三步：重启客户端

重启后即可使用 `search_ansa_api` 工具搜索 ANSA API。

## 使用示例

在客户端直接用自然语言描述需求，AI 会自动调用搜索工具：

```
你: 帮我写一个删除所有 shell 单元的脚本
AI: [调用 search_ansa_api("删除 shell")]
    → 找到 ansa.base.DeleteEntity()
    → 生成完整脚本
```

```
你: 如何获取某个 PID 下的所有单元？
AI: [调用 search_ansa_api("get elements by pid", module="ansa.base")]
    → 找到 ansa.base.CollectEntities()
    → 生成查询代码
```

### 搜索工具参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` | string | 搜索关键词，支持中英文 |
| `module` | string | 按模块过滤，如 `"ansa.mesh"` |
| `category` | string | 按分类过滤，如 `"mesh_edit"` |
| `top_n` | int | 返回结果数量，默认 5 |

## 技术架构

```
ansa-api-mcp/
├── ansa_tools/
│   ├── mcp_server.py                # MCP Server (FastMCP) + 三层搜索引擎
│   ├── parse_html.py                # Sphinx HTML 文档解析器
│   ├── generate_keywords.py         # AI 关键词生成 (Anthropic SDK)
│   ├── generate_index.py            # HTML 索引构建流水线
│   ├── generate_index_from_pydev.py # 基于 pydev 桩离线重建索引 (无需 API Key)
│   ├── merge_index.py               # 合并旧索引与 pydev 新接口
│   ├── ansa_api_index.json          # 预构建索引 (5892 函数 / v25.1.4)
│   └── txt_docs/                    # ANSA API 全量 TXT 文档 (26 个模块文件)
├── tests/                           # 测试套件
├── pyproject.toml                   # 包配置
└── demo/                            # 示例 ANSA 脚本
```

### 索引构建

索引通过以下流水线生成：

1. **HTML 解析** — 从 ANSA Sphinx 文档中提取函数签名、参数、描述、示例
2. **分类标注** — 根据函数名和模块自动分类（mesh_edit、base_query 等）
3. **关键词生成** — 调用 AI 为每个函数生成中英文搜索关键词
4. **输出索引** — 生成 `ansa_api_index.json`，供运行时搜索使用

### MCP 协议

本项目使用 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 的 FastMCP 框架，通过 stdio 协议与客户端通信。客户端在需要查询 ANSA API 时自动调用 `search_ansa_api` 工具。

## 高级配置

### 自定义 TXT 文档路径

如果你有更新版本的 ANSA TXT 文档，可通过环境变量覆盖内置文档。编辑 `~/.claude.json`：

```json
{
  "mcpServers": {
    "ansa-api": {
      "type": "stdio",
      "command": "ansa-api-mcp",
      "args": [],
      "env": {
        "ANSA_TXT_DOCS_PATH": "C:/path/to/your/txt_docs"
      }
    }
  }
}
```

### 重新生成索引

如果需要为不同版本的 ANSA 重新生成索引：

**方式 A：基于 ANSA HTML 文档（需要 Anthropic API Key 用于关键词生成）**

```bash
export ANTHROPIC_API_KEY="your-key"
python -m ansa_tools.generate_index
```

**方式 B：基于 pydev 自动补全桩（离线，无需 API Key / 网络）**

直接从 ANSA 安装目录的 pydev 桩文件重建，适合升级到新版本（如 v25.1.4）：

```bash
# 1) 用 pydev 桩重建 v25.1.4 接口索引
python -m ansa_tools.generate_index_from_pydev \
    "D:/Programs/BETA_CAE_Systems/ansa_v25.1.4/docs/extending/python_api/html/_downloads/autocomplete/py_dev/pydev_ansa/ansa"

# 2) 合并旧索引（保留富文档与 AI 关键词）与 pydev 新增接口，并回填关键词
python -m ansa_tools.merge_index
```

## 故障排查

### MCP 服务器在客户端中不可见

1. 确认配置写入了正确的文件：`~/.claude.json`（不是 `~/.claude/settings.json`）
2. 确认配置格式包含必要字段：
   ```json
   {
     "mcpServers": {
       "ansa-api": {
         "type": "stdio",
         "command": "C:\\path\\to\\ansa-api-mcp.EXE",
         "args": [],
         "env": {}
       }
     }
   }
   ```
3. 运行 `claude mcp list` 查看已注册的 MCP 服务器
4. 重启客户端

### pip install 报错 "Cannot find command 'git'"

说明没有安装 Git，请使用方式 B（zip 下载）安装。

## 开发

```bash
# 克隆仓库
git clone https://github.com/RufengLai/ansa-api-mcp.git
cd ansa-api-mcp

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v
```

## License

MIT
