# B站评论雷达（bilibili-comment-search）

**英文说明（GitHub 仓库默认首页）：** [README.md](README.md)

在 B 站单条视频下，从海量评论里**按你的问题挑出最相关的那几条**，少刷屏、少漏楼中楼。项目提供一个基于 [MCP](https://modelcontextprotocol.io) 的本地服务：拉取评论 → 去重 → 语义检索（embedding + 关键词混合）→ 可选 LLM 二次重排。

同目录下的 **`SKILL.md`** 供 AI 助手在对话中按需触发工作流。

---

## 项目介绍

### 能解决什么问题

- 视频很长、评论几千条，**手动翻半天**也找不到别人对你关心那点的说法。
- 热评往往是梗或情绪，**不一定回答你的具体问题**（比如续航、难度、是否劝退）。
- 有价值的讨论常出在**评论区深处**，容易漏看。

### 项目提供什么

| 能力 | 说明 |
|------|------|
| **单视频评论抓取** | 主评论分页；可选「深度楼中楼」继续翻子回复。 |
| **去重** | 按评论 ID 等方式合并重复条目。 |
| **相似评论检索** | 用小多语向量模型做语义相似度，辅以关键词与点赞微调。 |
| **向量缓存** | 同一 BV、同一批评论重复问时，可少算一遍评论向量。 |
| **可选 LLM 重排** | 配置 OpenAI 兼容 API 后，可对 Top 候选再做一轮精排。 |

### 技术栈（简要）

- Python 3.10+
- `mcp`（FastMCP）、`requests`、`sentence-transformers`、`numpy`；可选 `openai`。

### 局限（使用前请知悉）

- 抓取范围受接口与参数限制，**不是**「全宇宙每一条评论都入库」意义上的全量。
- 请求过快可能触发限流，内置了较短间隔；请合理使用。
- 结论仅反映**已抓取到的评论样本**，不能代替官方或权威结论。

---

## 用户使用指南

### 适用人群

- 常看 B 站测评、教程、热点视频，想**快速对齐评论区观点**的人。
- 已在使用 **Claude Desktop、MCP Inspector** 等支持 MCP 的环境，或任意能配置 **stdio 型 MCP** 的客户端，并愿意本地跑一个小服务的用户。

### 你需要准备什么

1. **Python 3.10+**（建议 3.10～3.12，以你本机环境为准）。
2. 克隆或已进入本项目目录 `bilibili-comment-search`。
3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. **首次使用语义检索**时，会自动下载 embedding 模型（体积约几百 MB），请保证网络或可提前离线配置缓存目录（见下文「性能与离线」）。

### 如何启动 MCP 服务

```bash
python mcp_server.py
```

正常配置下，客户端通过 **stdio** 与该进程通信；具体入口由各客户端的配置决定。

### 在常见客户端里接入 MCP（不必只用 Cursor）

本项目是 **stdio** 型 MCP：客户端会启动 `python mcp_server.py` 与本进程通信。只要你的软件支持「自定义命令 + 参数」添加 MCP，一般都能接入。**请把所有路径改成你本机上的绝对路径**（下面 Windows 路径仅为示例）。

#### 1. Claude Desktop

编辑配置文件后**完全退出再打开** Claude：

- Windows：`%APPDATA%\Claude\claude_desktop_config.json`
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "bilibili-comment-search": {
      "command": "python",
      "args": ["D:/skills/bilibili-comment-search/mcp_server.py"]
    }
  }
}
```

若系统里 `python` 不是 3.10+，可改成 `py -3.11` 或完整路径，例如 `"command": "C:\\Users\\你\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"`。

#### 2. MCP Inspector

不依赖付费 IDE，用于在浏览器里点选工具、看返回 JSON：

```bash
npx @modelcontextprotocol/inspector python D:/skills/bilibili-comment-search/mcp_server.py
```

（需已安装 Node.js；首次会下载 inspector。）

#### 3. Cursor

若你使用 Cursor：在 **Cursor Settings → MCP** 添加服务器，或项目内 `.cursor/mcp.json` 使用与上面相同的 `command` / `args` 即可。

保存或修改配置后，在客户端里**刷新 MCP 列表或重启应用**，应能看到工具（如 `fetch_video_comments_tool`、`search_similar_comments_tool`）。

### 在对话里怎么用

你**不用记工具名**，像和朋友说话即可，例如：

- 贴一个视频链接，再说：「评论区有没有人吐槽续航？」
- 「这个 BV，大家怎么说新手能不能跟？」
- 「上次给太少了，多翻点楼中楼再给我几条。」

前提是：**AI 客户端已加载本仓库的 `SKILL.md`，且 MCP 已连接**。助手会按技能说明去调用抓取与检索工具。

### 工具说明（供进阶用户调参）

暴露的两个主要工具（名称以客户端展示为准，常见后缀 `_tool`）：

**1. `fetch_video_comments` — 只拉评论，不做相似度排序**

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `bvid_or_url` | 必填 | 视频链接或 `BV` 号 |
| `max_pages` | 20 | 主评论列表翻页上限 |
| `sort` | `hot` | `hot` 或 `new` |
| `include_replies` | true | 是否包含子回复 |
| `deep_fetch_replies` | false | 是否对每条主评继续分页扒楼中楼 |
| `max_reply_pages_per_root` | 5 | 每条主评下子回复最多翻几页（没有那么多页会自动停） |
| `max_total_replies` | 1000 | 子回复全局大致上限，防刷爆 |

**2. `search_similar_comments` — 拉评论 + 按 `query` 排最相关 TopN**

在「抓取」参数基础上额外包括：

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `query` | 必填 | 你想对齐的话题或问题（自然语言） |
| `top_n` | 8 | 返回几条最相关评论 |
| `rerank_mode` | `hybrid` | 当前为 embedding + 关键词混合 |
| `embedding_model` | 见代码 | 默认多为 `paraphrase-multilingual-MiniLM-L12-v2` |
| `embedding_model_cache_dir` | `.cache/models` | 模型下载缓存目录 |
| `embedding_vector_cache_dir` | `.cache/embeddings` | 按 BV 缓存评论向量 |
| `embedding_local_files_only` | false | 仅使用本地已缓存模型 |
| `enable_llm_rerank` | false | 是否用 LLM 对候选再排一轮 |
| `llm_model` | `gpt-4.1-mini` | LLM 模型名（需 API） |
| `llm_rerank_top_k` | 30 | 送进 LLM 重排的候选条数 |

### 环境变量（可选）

部分赛事/上传平台**不允许**技能包里出现名为 `.env.example` 等敏感文件名，因此本仓库不附带该类文件。需要时在**本机系统环境变量**或 MCP 客户端配置里自行填写即可：

```text
# 当前代码不读取以下三项，不填也能正常使用；仅作将来若接入需登录态接口时的备忘。
# BILIBILI_SESSDATA=
# BILIBILI_BILI_JCT=
# BILIBILI_DEDEUSERID=

# LLM 二次重排（OpenAI 兼容）
# OPENAI_API_KEY=
# OPENAI_BASE_URL=

# Embedding 缓存目录（与代码中参数一致即可）
# EMBEDDING_MODEL_CACHE_DIR=.cache/models
# EMBEDDING_VECTOR_CACHE_DIR=.cache/embeddings
```

### 性能与离线

- **想快一点**：可把 `deep_fetch_replies` 设为 `false`，或减少 `max_pages`。
- **想全一点**：增大 `max_pages`、`max_reply_pages_per_root`、`max_total_replies`。
- **离线跑 embedding**：先把模型下载到本地缓存目录，再设 `embedding_local_files_only=true` 并指向该目录。

---

## 具体事例

下面是可以直接复制到对话里的说法（把链接或 BV 换成真实视频即可）。

### 事例 1：测评买不买，看评论怎么说续航

```text
我刷到这个测评懒得翻评论了，你帮我看看有没有人吐槽续航缩水或者虚标？
https://www.bilibili.com/video/BVxxxxxxxx
先说评论区大概啥风向，再贴几条最相关的原话。
```

### 事例 2：教程能不能跟，有没有人劝退

```text
BVxxxxxxxx 这个教学我想学，但我纯小白。
你从评论里翻翻有没有说跟不上、太难、劝退之类的，多给几条，楼里的也行。
```

### 事例 3：只想看跟「噪音」相关的说法

```text
这个视频评论里大家对「噪音」咋说的？给我挑最相关的 5 条，带上为啥选它们。
链接：……
```

### 事例 4：觉得上次给少了，要多扒楼中楼

```text
上次那几条不够，你再捞一轮，楼中楼也翻翻，最后还是给我个五六条最贴我问题的。
```

### 事例 5：觉得排序不准，想再精一点

```text
你这前面几条不太贴我问的「夜间噪声」，能不能再精细筛一遍？不行就告诉我差在哪儿。
```

（若已配置 LLM，可说明「打开高精度重排」；否则助手会按混合排序解释限制。）

---

## 仓库结构

```text
bilibili-comment-search/
├── SKILL.md              # AI 助手侧技能说明（触发与工作流）
├── README.md             # 英文说明（GitHub 默认首页）
├── README.zh-CN.md       # 本文件：中文说明
├── mcp_server.py         # MCP 入口与工具注册
├── bilibili_client.py    # B 站接口与评论分页、楼中楼
├── ranking.py            # 向量相似度、混合排序、可选 LLM 重排
├── models.py             # 数据结构
└── requirements.txt
```

（环境变量说明见上文「环境变量（可选）」，勿在压缩包内包含 `.env.example` 等易被平台拦截的文件名。）

## 许可证与合规

- 请遵守 B 站服务条款与合理使用规范，勿高频滥用接口。
- 第三方 MCP 与公开 API 可能变更，如运行报错请优先检查网络与接口返回信息。
