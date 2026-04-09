from __future__ import annotations

import math
import os
import re
from pathlib import Path
from collections import Counter
from typing import Any

from models import CommentItem, SearchResultItem

TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")

_EMBEDDING_MODEL: Any | None = None


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _get_embedding_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Any:
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "未安装 sentence-transformers，无法使用 embedding 相似度。"
            "请先 pip install -r requirements.txt"
        ) from e

    _EMBEDDING_MODEL = SentenceTransformer(model_name)
    return _EMBEDDING_MODEL


def _get_embedding_model_with_options(
    model_name: str,
    cache_folder: str | None = None,
    local_files_only: bool = False,
) -> Any:
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "未安装 sentence-transformers，无法使用 embedding 相似度。"
            "请先 pip install -r requirements.txt"
        ) from e

    kwargs: dict[str, Any] = {"local_files_only": local_files_only}
    if cache_folder:
        kwargs["cache_folder"] = cache_folder
    _EMBEDDING_MODEL = SentenceTransformer(model_name, **kwargs)
    return _EMBEDDING_MODEL


def _cosine_similarity(a: Any, b: Any) -> float:
    import numpy as np  # local import to keep base import fast

    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
    return float(np.dot(a, b) / denom)


def _comment_key(item: CommentItem) -> str:
    if item.comment_id:
        return item.comment_id
    return f"{item.root_comment_id}:{item.text[:200]}"


def _sanitize_model_name(model_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_name)


def _load_or_build_comment_embeddings(
    model: Any,
    comments: list[CommentItem],
    bvid: str | None,
    model_name: str,
    vector_cache_dir: str | None,
):
    import json
    import numpy as np

    texts = [c.text.strip() if c.text.strip() else " " for c in comments]
    keys = [_comment_key(c) for c in comments]

    if not bvid or not vector_cache_dir:
        vecs = model.encode(texts, normalize_embeddings=True)
        return vecs

    cache_root = Path(vector_cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    model_part = _sanitize_model_name(model_name)
    cache_json = cache_root / f"{bvid}.{model_part}.meta.json"
    cache_npy = cache_root / f"{bvid}.{model_part}.vec.npy"

    if cache_json.exists() and cache_npy.exists():
        try:
            with cache_json.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            cached_keys = meta.get("keys") or []
            if cached_keys == keys:
                return np.load(cache_npy)
        except Exception:
            # Any cache corruption falls back to recompute.
            pass

    vecs = model.encode(texts, normalize_embeddings=True)
    try:
        with cache_json.open("w", encoding="utf-8") as f:
            json.dump({"keys": keys, "count": len(keys)}, f, ensure_ascii=False)
        np.save(cache_npy, vecs)
    except Exception:
        # Cache write failure should not break retrieval.
        pass
    return vecs


def _keyword_overlap_score(query_tokens: list[str], comment_tokens: list[str]) -> float:
    if not query_tokens or not comment_tokens:
        return 0.0
    q_counter = Counter(query_tokens)
    c_counter = Counter(comment_tokens)
    overlap = 0
    for k, qv in q_counter.items():
        overlap += min(qv, c_counter.get(k, 0))
    return overlap / max(len(query_tokens), 1)


def hybrid_rank(
    query: str,
    comments: list[CommentItem],
    top_n: int = 8,
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    bvid: str | None = None,
    model_cache_dir: str | None = None,
    local_files_only: bool = False,
    vector_cache_dir: str | None = ".cache/embeddings",
) -> list[SearchResultItem]:
    """
    Hybrid ranking:
    - embedding cosine similarity (primary)
    - keyword overlap (secondary)
    - small like boost
    """
    import numpy as np

    q_tokens = _tokenize(query)
    env_model_cache = os.environ.get("EMBEDDING_MODEL_CACHE_DIR")
    env_vector_cache = os.environ.get("EMBEDDING_VECTOR_CACHE_DIR")
    if not model_cache_dir and env_model_cache:
        model_cache_dir = env_model_cache
    if not vector_cache_dir and env_vector_cache:
        vector_cache_dir = env_vector_cache

    model = _get_embedding_model_with_options(
        model_name=embedding_model,
        cache_folder=model_cache_dir,
        local_files_only=local_files_only,
    )

    texts = [c.text.strip() for c in comments]
    q_vec = model.encode([query], normalize_embeddings=True)[0]
    c_vecs = _load_or_build_comment_embeddings(
        model=model,
        comments=comments,
        bvid=bvid,
        model_name=embedding_model,
        vector_cache_dir=vector_cache_dir,
    )

    scored: list[tuple[float, str, CommentItem, float, float]] = []
    for idx, item in enumerate(comments):
        text = texts[idx]
        if not text:
            continue
        c_tokens = _tokenize(text)
        keyword = _keyword_overlap_score(q_tokens, c_tokens)  # 0~1

        # cosine similarity in [-1, 1] -> clamp to [0, 1] for readability
        emb_raw = float(np.dot(q_vec, c_vecs[idx]))
        emb = max(min((emb_raw + 1.0) / 2.0, 1.0), 0.0)

        like_boost = min(math.log1p(max(item.like, 0)) / 10.0, 0.2)
        short_penalty = 0.08 if len(text) <= 3 else 0.0
        score = 0.75 * emb + 0.2 * keyword + like_boost - short_penalty
        reason = _build_reason(keyword=keyword, semantic=emb, likes=item.like)
        scored.append((score, reason, item, emb, keyword))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(top_n, 1)]
    return [
        SearchResultItem(
            rank=idx + 1,
            score=round(max(min(score, 1.0), 0.0), 4),
            reason=reason,
            comment=item,
        )
        for idx, (score, reason, item, _emb, _kw) in enumerate(top)
    ]


def llm_rerank(
    query: str,
    candidates: list[SearchResultItem],
    model: str = "gpt-4.1-mini",
) -> list[SearchResultItem]:
    """
    Optional LLM re-rank using OpenAI-compatible API.
    Requires env var OPENAI_API_KEY.
    """
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("未安装 openai 包，无法启用 LLM rerank。") from e

    client = OpenAI()
    items = [
        {
            "idx": i,
            "text": c.comment.text,
            "like": c.comment.like,
            "ctime": c.comment.ctime,
        }
        for i, c in enumerate(candidates)
    ]

    prompt = (
        "你是评论检索的重排器。给定用户问题与候选评论列表，请按“与问题的语义相关度”从高到低排序。"
        "只输出 JSON：{order:[idx...], reasons:{idx:reason}}。reason 用中文短句（<=20字）。"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"问题：{query}\n候选：{items}"},
        ],
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    import json

    data = json.loads(content)
    order = data.get("order") or []
    reasons = data.get("reasons") or {}

    reranked: list[SearchResultItem] = []
    for new_rank, idx in enumerate(order):
        try:
            idx_int = int(idx)
        except Exception:
            continue
        if idx_int < 0 or idx_int >= len(candidates):
            continue
        base = candidates[idx_int]
        base.rank = new_rank + 1
        base.reason = str(reasons.get(str(idx_int)) or reasons.get(idx_int) or base.reason)
        reranked.append(base)

    # Fallback: if parsing failed, keep original order
    return reranked if reranked else candidates


def _build_reason(keyword: float, semantic: float, likes: int) -> str:
    reasons: list[str] = []
    if keyword >= 0.4:
        reasons.append("关键词命中高")
    elif keyword >= 0.2:
        reasons.append("关键词部分命中")

    if semantic >= 0.4:
        reasons.append("语义相似度高")
    elif semantic >= 0.2:
        reasons.append("语义有一定相关性")

    if likes > 100:
        reasons.append("点赞较高")

    if not reasons:
        return "语义弱相关"
    return "，".join(reasons)
