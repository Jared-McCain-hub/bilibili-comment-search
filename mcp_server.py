from __future__ import annotations

from typing import Any

from bilibili_client import BilibiliClient
from ranking import hybrid_rank, llm_rerank

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None


client = BilibiliClient()
mcp = FastMCP("bilibili-comment-search") if FastMCP else None


def _dedupe_comments(raw_comments: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in raw_comments:
        key = item.comment_id or f"{item.root_comment_id}:{item.text}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def fetch_video_comments(
    bvid_or_url: str,
    max_pages: int = 20,
    sort: str = "hot",
    include_replies: bool = True,
    deep_fetch_replies: bool = False,
    max_reply_pages_per_root: int = 5,
    max_total_replies: int = 1000,
) -> dict[str, Any]:
    bvid = client.resolve_bvid(bvid_or_url)
    video = client.get_video_info(bvid)
    aid = client.get_aid(bvid)
    raw_comments, pages_fetched = client.fetch_comments(
        aid=aid,
        max_pages=max_pages,
        sort=sort,
        include_replies=include_replies,
        deep_fetch_replies=deep_fetch_replies,
        max_reply_pages_per_root=max_reply_pages_per_root,
        max_total_replies=max_total_replies,
    )
    deduped = _dedupe_comments(raw_comments)
    return {
        "video": video.to_dict(),
        "stats": {
            "pages_fetched": pages_fetched,
            "comments_total": len(raw_comments),
            "deduped_total": len(deduped),
        },
        "comments": [c.to_dict() for c in deduped],
    }


def search_similar_comments(
    bvid_or_url: str,
    query: str,
    top_n: int = 8,
    max_pages: int = 20,
    sort: str = "hot",
    include_replies: bool = True,
    deep_fetch_replies: bool = False,
    max_reply_pages_per_root: int = 5,
    max_total_replies: int = 1000,
    rerank_mode: str = "hybrid",
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    embedding_model_cache_dir: str | None = ".cache/models",
    embedding_local_files_only: bool = False,
    embedding_vector_cache_dir: str | None = ".cache/embeddings",
    enable_llm_rerank: bool = False,
    llm_model: str = "gpt-4.1-mini",
    llm_rerank_top_k: int = 30,
) -> dict[str, Any]:
    if rerank_mode != "hybrid":
        raise ValueError("当前仅支持 rerank_mode=hybrid")

    fetched = fetch_video_comments(
        bvid_or_url=bvid_or_url,
        max_pages=max_pages,
        sort=sort,
        include_replies=include_replies,
        deep_fetch_replies=deep_fetch_replies,
        max_reply_pages_per_root=max_reply_pages_per_root,
        max_total_replies=max_total_replies,
    )
    comments = fetched["comments"]

    # Convert dict comments back into lightweight objects for ranking.
    # This avoids duplicated network calls and keeps sorting pure.
    class _Item:
        def __init__(self, payload: dict[str, Any]):
            self.comment_id = payload.get("comment_id", "")
            self.root_comment_id = payload.get("root_comment_id", "")
            self.text = payload.get("text", "")
            self.like = int(payload.get("like", 0))
            self.reply_count = int(payload.get("reply_count", 0))
            self.ctime = int(payload.get("ctime", 0))
            self.parent_comment_id = payload.get("parent_comment_id")
            self.is_reply = bool(payload.get("is_reply", False))
            self.user = payload.get("user", {})

        def to_dict(self) -> dict[str, Any]:
            return {
                "comment_id": self.comment_id,
                "root_comment_id": self.root_comment_id,
                "parent_comment_id": self.parent_comment_id,
                "text": self.text,
                "like": self.like,
                "reply_count": self.reply_count,
                "ctime": self.ctime,
                "is_reply": self.is_reply,
                "user": self.user,
            }

    rank_items = [_Item(c) for c in comments]
    ranked = hybrid_rank(
        query=query,
        comments=rank_items,
        top_n=max(top_n, llm_rerank_top_k) if enable_llm_rerank else top_n,
        embedding_model=embedding_model,
        bvid=str(fetched["video"].get("bvid", "")),
        model_cache_dir=embedding_model_cache_dir,
        local_files_only=embedding_local_files_only,
        vector_cache_dir=embedding_vector_cache_dir,
    )
    if enable_llm_rerank:
        ranked = llm_rerank(query=query, candidates=ranked[: max(llm_rerank_top_k, top_n)], model=llm_model)[
            : max(top_n, 1)
        ]
    return {
        "query": query,
        "video": fetched["video"],
        "results": [r.to_dict() for r in ranked],
        "debug": {
            "candidate_count": len(comments),
            "deep_fetch_replies": deep_fetch_replies,
            "max_reply_pages_per_root": max_reply_pages_per_root,
            "max_total_replies": max_total_replies,
            "recall_mode": "keyword+embedding",
            "rerank_mode": rerank_mode,
            "embedding_model": embedding_model,
            "embedding_model_cache_dir": embedding_model_cache_dir,
            "embedding_local_files_only": embedding_local_files_only,
            "embedding_vector_cache_dir": embedding_vector_cache_dir,
            "enable_llm_rerank": enable_llm_rerank,
            "llm_model": llm_model if enable_llm_rerank else None,
        },
    }


if mcp:

    @mcp.tool()
    def fetch_video_comments_tool(
        bvid_or_url: str,
        max_pages: int = 20,
        sort: str = "hot",
        include_replies: bool = True,
        deep_fetch_replies: bool = False,
        max_reply_pages_per_root: int = 5,
        max_total_replies: int = 1000,
    ) -> dict[str, Any]:
        return fetch_video_comments(
            bvid_or_url=bvid_or_url,
            max_pages=max_pages,
            sort=sort,
            include_replies=include_replies,
            deep_fetch_replies=deep_fetch_replies,
            max_reply_pages_per_root=max_reply_pages_per_root,
            max_total_replies=max_total_replies,
        )

    @mcp.tool()
    def search_similar_comments_tool(
        bvid_or_url: str,
        query: str,
        top_n: int = 8,
        max_pages: int = 20,
        sort: str = "hot",
        include_replies: bool = True,
        deep_fetch_replies: bool = False,
        max_reply_pages_per_root: int = 5,
        max_total_replies: int = 1000,
        rerank_mode: str = "hybrid",
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedding_model_cache_dir: str | None = ".cache/models",
        embedding_local_files_only: bool = False,
        embedding_vector_cache_dir: str | None = ".cache/embeddings",
        enable_llm_rerank: bool = False,
        llm_model: str = "gpt-4.1-mini",
        llm_rerank_top_k: int = 30,
    ) -> dict[str, Any]:
        return search_similar_comments(
            bvid_or_url=bvid_or_url,
            query=query,
            top_n=top_n,
            max_pages=max_pages,
            sort=sort,
            include_replies=include_replies,
            deep_fetch_replies=deep_fetch_replies,
            max_reply_pages_per_root=max_reply_pages_per_root,
            max_total_replies=max_total_replies,
            rerank_mode=rerank_mode,
            embedding_model=embedding_model,
            embedding_model_cache_dir=embedding_model_cache_dir,
            embedding_local_files_only=embedding_local_files_only,
            embedding_vector_cache_dir=embedding_vector_cache_dir,
            enable_llm_rerank=enable_llm_rerank,
            llm_model=llm_model,
            llm_rerank_top_k=llm_rerank_top_k,
        )


if __name__ == "__main__":
    if not mcp:
        raise RuntimeError("请先安装 mcp>=1.0.0 后再运行 MCP Server")
    mcp.run()
