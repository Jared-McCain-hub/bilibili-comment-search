from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class VideoInfo:
    bvid: str
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommentItem:
    comment_id: str
    root_comment_id: str
    parent_comment_id: str | None
    text: str
    like: int
    reply_count: int
    ctime: int
    is_reply: bool
    user: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResultItem:
    rank: int
    score: float
    reason: str
    comment: CommentItem

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["comment"] = self.comment.to_dict()
        return payload
