from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from models import CommentItem, VideoInfo

BV_RE = re.compile(r"(BV[0-9A-Za-z]+)")


class BilibiliClient:
    def __init__(self, timeout: int = 15, sleep_seconds: float = 0.35):
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
            }
        )

    def resolve_bvid(self, bvid_or_url: str) -> str:
        direct = BV_RE.search(bvid_or_url)
        if direct:
            return direct.group(1)

        parsed = urlparse(bvid_or_url)
        query = parse_qs(parsed.query)
        if "bvid" in query and query["bvid"]:
            return query["bvid"][0]

        raise ValueError("无法从输入中解析 BV 号，请传入 BVxxxx 或视频 URL")

    def get_video_info(self, bvid: str) -> VideoInfo:
        url = "https://api.bilibili.com/x/web-interface/view"
        resp = self.session.get(url, params={"bvid": bvid}, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0 or "data" not in payload:
            raise RuntimeError(f"获取视频信息失败: {payload}")
        data = payload["data"] or {}
        return VideoInfo(bvid=bvid, title=data.get("title", ""))

    def get_aid(self, bvid: str) -> int:
        url = "https://api.bilibili.com/x/web-interface/view"
        resp = self.session.get(url, params={"bvid": bvid}, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0 or "data" not in payload:
            raise RuntimeError(f"获取 aid 失败: {payload}")
        aid = (payload["data"] or {}).get("aid")
        if not aid:
            raise RuntimeError("接口未返回有效 aid")
        return int(aid)

    def fetch_comments(
        self,
        aid: int,
        max_pages: int = 20,
        sort: str = "hot",
        include_replies: bool = True,
        deep_fetch_replies: bool = False,
        max_reply_pages_per_root: int = 5,
        max_total_replies: int = 1000,
    ) -> tuple[list[CommentItem], int]:
        all_items: list[CommentItem] = []
        page_count = 0
        fetched_reply_count = 0
        mode = 3 if sort == "new" else 2  # 2=hot, 3=time

        for page in range(1, max_pages + 1):
            page_count += 1
            url = "https://api.bilibili.com/x/v2/reply"
            params = {"type": 1, "oid": aid, "pn": page, "ps": 20, "sort": mode}
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("code") != 0:
                raise RuntimeError(f"评论接口返回错误: {payload}")

            data = payload.get("data") or {}
            replies = data.get("replies") or []
            if not replies:
                break

            for root in replies:
                root_id = str(root.get("rpid", ""))
                all_items.append(self._reply_to_comment(root, is_reply=False, root_id=root_id))
                if not include_replies:
                    continue

                # Include shallow replies that come with the root payload.
                for child in (root.get("replies") or []):
                    all_items.append(self._reply_to_comment(child, is_reply=True, root_id=root_id))
                    fetched_reply_count += 1

                # Optionally continue paging sub-replies for deeper coverage.
                if deep_fetch_replies and fetched_reply_count < max_total_replies:
                    remaining = max_total_replies - fetched_reply_count
                    deep_children = self._fetch_sub_replies(
                        aid=aid,
                        root_id=root_id,
                        max_reply_pages=max_reply_pages_per_root,
                        max_fetch=remaining,
                    )
                    all_items.extend(deep_children)
                    fetched_reply_count += len(deep_children)

            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)

        return all_items, page_count

    def _fetch_sub_replies(
        self,
        aid: int,
        root_id: str,
        max_reply_pages: int,
        max_fetch: int,
    ) -> list[CommentItem]:
        items: list[CommentItem] = []
        if max_fetch <= 0:
            return items

        for pn in range(1, max_reply_pages + 1):
            url = "https://api.bilibili.com/x/v2/reply/reply"
            params = {
                "type": 1,
                "oid": aid,
                "root": root_id,
                "pn": pn,
                "ps": 20,
            }
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                break

            data = payload.get("data") or {}
            replies = data.get("replies") or []
            if not replies:
                break

            for raw in replies:
                items.append(self._reply_to_comment(raw, is_reply=True, root_id=root_id))
                if len(items) >= max_fetch:
                    return items

            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)

        return items

    def _reply_to_comment(self, raw: dict[str, Any], is_reply: bool, root_id: str) -> CommentItem:
        member = raw.get("member") or {}
        content = raw.get("content") or {}
        return CommentItem(
            comment_id=str(raw.get("rpid") or ""),
            root_comment_id=root_id,
            parent_comment_id=str(raw.get("parent")) if raw.get("parent") else None,
            text=(content.get("message") or "").strip(),
            like=int(raw.get("like") or 0),
            reply_count=int(raw.get("rcount") or 0),
            ctime=int(raw.get("ctime") or 0),
            is_reply=is_reply,
            user={
                "uid": str(member.get("mid") or ""),
                "uname": member.get("uname") or "",
            },
        )
