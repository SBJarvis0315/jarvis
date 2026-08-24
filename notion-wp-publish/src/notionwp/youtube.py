"""고객사 유튜브 채널의 영상 목록을 가져옵니다.

원고에 어울리는 영상을 발행 단계에서 골라 본문에 끼워 넣기 위한 후보 목록입니다.
어떤 영상을 고를지는 사람이나 루틴 안의 Claude 가 plan.json 에서 정합니다.
여기서는 '무엇이 있는지'만 알려줍니다.

경로가 둘입니다.
  · YOUTUBE_API_KEY 가 있으면 Data API 로 채널의 **전체** 영상을 가져옵니다.
  · 없으면 채널 RSS 로 **최신 15개**만 가져옵니다. 키 없이도 동작은 하되,
    오래된 영상이 후보에서 빠지므로 주제가 어긋나는 일이 잦아집니다.

영상은 있으면 좋은 부가 요소입니다. 여기서 무슨 일이 생겨도 발행을 막지 않습니다.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/youtube/v3"
RSS_URL = "https://www.youtube.com/feeds/videos.xml"
TIMEOUT = 20

#: 후보가 너무 많으면 고르는 쪽이 오히려 힘들어집니다.
MAX_VIDEOS = 200

_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_HANDLE = re.compile(r"@[A-Za-z0-9_.-]+")


@dataclass
class Video:
    video_id: str
    title: str
    published: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def api_key(env: dict[str, str] | None = None) -> str:
    src: Any = env if env is not None else os.environ
    return (src.get("YOUTUBE_API_KEY") or "").strip()


def parse_channel(value: str) -> tuple[str, str]:
    """설정표에 적힌 값에서 채널을 알아냅니다 → (channel_id, handle).

    `UC...` · `@핸들` · 채널 주소 아무 형태나 받습니다. 사람이 손으로 붙여넣는
    칸이라 형식을 따지지 않습니다.
    """
    text = (value or "").strip()
    if not text:
        return "", ""

    found_id = _CHANNEL_ID.search(text)
    if found_id:
        return found_id.group(0), ""

    found_handle = _HANDLE.search(text)
    if found_handle:
        return "", found_handle.group(0)

    # 'youtube.com/c/이름' 처럼 핸들도 ID도 없는 옛 주소.
    tail = text.rstrip("/").rsplit("/", 1)[-1]
    return ("", "@" + tail) if tail and "youtube" not in tail.lower() else ("", "")


def _get(session: requests.Session | None, url: str, params: dict[str, Any]) -> dict[str, Any]:
    sess = session or requests
    resp = sess.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _uploads_playlist(
    channel_id: str, handle: str, key: str, session: requests.Session | None
) -> tuple[str, str]:
    """채널의 '업로드' 재생목록 ID를 찾습니다 → (playlist_id, channel_id)."""
    params: dict[str, Any] = {"part": "contentDetails", "key": key}
    if channel_id:
        params["id"] = channel_id
    else:
        params["forHandle"] = handle

    items = _get(session, f"{API_ROOT}/channels", params).get("items") or []
    if not items:
        raise LookupError(f"채널을 찾지 못했습니다: {channel_id or handle}")

    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return uploads, items[0].get("id", channel_id)


def _from_api(
    channel_id: str, handle: str, key: str, session: requests.Session | None, limit: int
) -> list[Video]:
    playlist, _ = _uploads_playlist(channel_id, handle, key, session)

    videos: list[Video] = []
    page: str | None = None

    while len(videos) < limit:
        params: dict[str, Any] = {
            "part": "snippet",
            "playlistId": playlist,
            "maxResults": 50,
            "key": key,
        }
        if page:
            params["pageToken"] = page

        data = _get(session, f"{API_ROOT}/playlistItems", params)
        for item in data.get("items") or []:
            snippet = item.get("snippet") or {}
            vid = (snippet.get("resourceId") or {}).get("videoId")
            title = (snippet.get("title") or "").strip()
            # 비공개·삭제된 영상은 제목이 자리표시자로 바뀝니다. 후보에서 뺍니다.
            if vid and title and title not in ("Private video", "Deleted video"):
                videos.append(Video(vid, title, (snippet.get("publishedAt") or "")[:10]))

        page = data.get("nextPageToken")
        if not page:
            break

    return videos[:limit]


def _from_rss(channel_id: str, session: requests.Session | None) -> list[Video]:
    sess = session or requests
    resp = sess.get(RSS_URL, params={"channel_id": channel_id}, timeout=TIMEOUT)
    resp.raise_for_status()

    videos: list[Video] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", resp.text, re.S):
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry)
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        published = re.search(r"<published>(.*?)</published>", entry)
        if vid and title:
            videos.append(
                Video(vid.group(1), title.group(1).strip(), (published.group(1) if published else "")[:10])
            )
    return videos


def list_videos(
    channel: str,
    *,
    key: str = "",
    session: requests.Session | None = None,
    limit: int = MAX_VIDEOS,
) -> list[Video]:
    """채널의 영상 목록. 실패하면 빈 목록을 돌려주고 발행은 그대로 진행합니다."""
    channel_id, handle = parse_channel(channel)
    if not channel_id and not handle:
        return []

    if key:
        try:
            return _from_api(channel_id, handle, key, session, limit)
        except Exception as exc:
            log.warning("유튜브 API 조회에 실패해 RSS로 물러납니다: %s", exc)

    if not channel_id:
        log.warning(
            "API 키 없이는 채널 ID(UC…)가 필요합니다. 설정표의 유튜브 채널 칸에 "
            "채널 ID를 넣거나 YOUTUBE_API_KEY 를 설정해 주세요: %s", channel
        )
        return []

    try:
        return _from_rss(channel_id, session)
    except Exception as exc:
        log.warning("유튜브 RSS 조회에 실패했습니다: %s", exc)
        return []
