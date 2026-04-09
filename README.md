# Bilibili Comment Radar (`bilibili-comment-search`)

For a **single Bilibili video**, find the **most relevant comments to your question** without endless scrolling, with optional deep pagination into nested replies (“楼中楼”). This repo ships a local [MCP](https://modelcontextprotocol.io) server: fetch comments → dedupe → semantic search (embeddings + keyword blend) → optional LLM rerank.

**`SKILL.md`** in the same folder tells AI assistants when and how to run this workflow.

**[简体中文 Chinese README → README.zh-CN.md](README.zh-CN.md)**

---

## Overview

### Problems it helps with

- Long videos and thousands of comments—**hard to find** what others said about *your* topic.
- Top comments are often memes or vibes, **not answers** to specific questions (battery life, difficulty, “should I buy”, etc.).
- Useful takes often sit in **nested threads**, easy to miss.

### What you get

| Feature | Description |
|--------|-------------|
| **Single-video comment fetch** | Paginated top-level comments; optional **deep nested-reply** fetching. |
| **Deduping** | Merges duplicates (e.g. by comment id). |
| **Similar-comment search** | Multilingual embedding similarity plus keyword signal and light like-weighting. |
| **Vector cache** | Re-querying the same BV with the same comment set can skip re-encoding comments. |
| **Optional LLM rerank** | With an OpenAI-compatible API, rerank top candidates for sharper ordering. |

### Stack (short)

- Python 3.10+
- `mcp` (FastMCP), `requests`, `sentence-transformers`, `numpy`; optional `openai`.

### Limitations

- Coverage is bounded by APIs and your parameters—not a guarantee of “every comment ever”.
- Aggressive request rates may hit throttling; the client uses short delays—use responsibly.
- Output reflects **only the fetched sample**, not an official or authoritative verdict.

---

## User guide

### Who it’s for

- People who watch reviews, tutorials, or trending videos on Bilibili and want **comment-section signal fast**.
- Anyone running **Claude Desktop**, **MCP Inspector**, or any MCP client that supports **stdio** servers.

### Prerequisites

1. **Python 3.10+** (3.10–3.12 recommended).
2. Clone or `cd` into `bilibili-comment-search`.
3. Install deps:

```bash
pip install -r requirements.txt
```

4. **First semantic search** downloads an embedding model (on the order of hundreds of MB). Ensure network access or preconfigure offline cache (see **Performance & offline**).

### Run the MCP server

```bash
python mcp_server.py
```

Clients talk to this process over **stdio**; exact wiring depends on the client.

### Connect from common MCP clients (not Cursor-only)

This is a **stdio** MCP server: the client runs `python mcp_server.py`. Any client that can register a custom command + args should work. **Use absolute paths on your machine** (examples below use Windows-style paths).

#### 1. Claude Desktop

Quit Claude fully, edit the config, then reopen.

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

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

If `python` is not 3.10+, use `py -3.11` or a full interpreter path, e.g. `"command": "C:\\Users\\you\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"`.

#### 2. MCP Inspector

Free debugging UI in the browser—invoke tools and inspect JSON:

```bash
npx @modelcontextprotocol/inspector python D:/skills/bilibili-comment-search/mcp_server.py
```

Requires Node.js; first run downloads the inspector.

#### 3. Cursor

**Cursor Settings → MCP**, or project `.cursor/mcp.json`, using the same `command` / `args` as above.

After saving, refresh MCP or restart the app. You should see tools such as `fetch_video_comments_tool` and `search_similar_comments_tool`.

### How to use in chat

You don’t need tool names—just natural language, for example:

- Paste a video URL and ask: “Does anyone in the comments complain about battery life?”
- “For this BV, what do people say about whether beginners can follow along?”
- “Last time was too few—dig nested replies and give me a few more.”

Requires: **`SKILL.md` loaded in the assistant** and **MCP connected**.

### Tool reference (power users)

Tool names in UIs may end with `_tool`.

**1. `fetch_video_comments` — fetch only, no similarity ranking**

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `bvid_or_url` | required | Video URL or `BV` id |
| `max_pages` | 20 | Max pages of top-level comments |
| `sort` | `hot` | `hot` or `new` |
| `include_replies` | true | Include shallow nested replies |
| `deep_fetch_replies` | false | Paginate deeper into nested replies per root |
| `max_reply_pages_per_root` | 5 | Max nested-reply pages per root (stops early if fewer exist) |
| `max_total_replies` | 1000 | Rough global cap on nested replies fetched |

**2. `search_similar_comments` — fetch + rank top-N by `query`**

Same fetch-related parameters as above, plus:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `query` | required | Your question or topic (natural language) |
| `top_n` | 8 | How many comments to return |
| `rerank_mode` | `hybrid` | Embedding + keyword hybrid |
| `embedding_model` | see code | Default often `paraphrase-multilingual-MiniLM-L12-v2` |
| `embedding_model_cache_dir` | `.cache/models` | Model download cache |
| `embedding_vector_cache_dir` | `.cache/embeddings` | Per-BV comment vector cache |
| `embedding_local_files_only` | false | Only use locally cached models |
| `enable_llm_rerank` | false | LLM rerank pass |
| `llm_model` | `gpt-4.1-mini` | LLM id (needs API) |
| `llm_rerank_top_k` | 30 | Candidates sent to LLM rerank |

### Environment variables (optional)

Some competition / upload platforms **forbid** files like `.env.example` in skill bundles, so this repo does **not** ship one. Set variables in your OS or client config if needed:

```text
# The following are NOT read by the current codebase. Others can use the project without them.
# Only relevant if you later wire logged-in/cookie-based APIs.
# BILIBILI_SESSDATA=
# BILIBILI_BILI_JCT=
# BILIBILI_DEDEUSERID=

# LLM rerank (OpenAI-compatible)
# OPENAI_API_KEY=
# OPENAI_BASE_URL=

# Embedding cache dirs (must match tool params if you override)
# EMBEDDING_MODEL_CACHE_DIR=.cache/models
# EMBEDDING_VECTOR_CACHE_DIR=.cache/embeddings
```

### Performance & offline

- **Faster**: `deep_fetch_replies=false` and/or lower `max_pages`.
- **Broader**: raise `max_pages`, `max_reply_pages_per_root`, `max_total_replies`.
- **Offline embeddings**: download the model once, then `embedding_local_files_only=true` and point `embedding_model_cache_dir` at the cache.

---

## Example prompts

Copy-paste into chat (replace URL or BV with a real video).

### 1. Review video—battery / range concerns

```text
I found this review and don’t want to scroll comments. Does anyone say battery life is overstated or worse than advertised?
https://www.bilibili.com/video/BVxxxxxxxx
Summarize the overall vibe, then quote the most relevant comments.
```

### 2. Tutorial—too hard for beginners?

```text
BVxxxxxxxx — I’m a total beginner. Scan comments for “too hard”, “can’t keep up”, or discouragement, including nested replies if useful.
```

### 3. Noise only

```text
What do comments say about “noise”? Give me the 5 most relevant and briefly why you picked them.
Link: …
```

### 4. Need more coverage

```text
That was too thin—fetch again with more nested threads, still give me ~5 that best match my question.
```

### 5. Ranking feels off

```text
The top results don’t match “nighttime noise” well—can you refine the ranking? If not, explain what’s limiting you.
```

(With LLM configured, you can ask to “enable high-precision rerank”; otherwise the assistant stays on hybrid ranking and explains limits.)

---

## Repository layout

```text
bilibili-comment-search/
├── SKILL.md              # Agent skill (triggers & workflow)
├── README.md             # This file (English, default on GitHub)
├── README.zh-CN.md       # Chinese readme
├── mcp_server.py         # MCP entry & tool registration
├── bilibili_client.py    # Bilibili HTTP client, pagination, nested replies
├── ranking.py            # Embeddings, hybrid rank, optional LLM rerank
├── models.py             # Data shapes
└── requirements.txt
```

Do **not** bundle disallowed filenames (e.g. `.env.example`) if your platform scans uploads.

## License & compliance

- Follow Bilibili’s terms and use reasonable request rates.
- Public APIs and behavior may change—check network and API responses when debugging.
