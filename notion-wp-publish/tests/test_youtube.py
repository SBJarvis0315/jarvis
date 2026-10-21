"""고객사 유튜브 채널 연동 — 후보 수집, 선택, 본문 삽입.

영상은 있으면 좋은 부가 요소입니다. 조회가 실패하거나 맞는 영상이 없어도
발행 자체는 그대로 되어야 합니다.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests

from fixtures import sample_page
from notionwp.gutenberg import render, video_block
from notionwp.plan import PagePlan, VideoChoice
from notionwp.publish import Publisher
from notionwp.youtube import list_videos, parse_channel
from test_gate_schema import CONFIG, complete_page, registry_row
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: F401


# ------------------------------------------------------------------ 채널 해석


def test_channel_value_accepts_whatever_a_person_pastes():
    assert parse_channel("UChmgWO96vv-GWfEFdsGnOHw") == ("UChmgWO96vv-GWfEFdsGnOHw", "")
    assert parse_channel("https://www.youtube.com/@CleartoneClinic") == ("", "@CleartoneClinic")
    assert parse_channel("@CleartoneClinic") == ("", "@CleartoneClinic")
    assert parse_channel("") == ("", "")


def test_registry_carries_the_channel_through():
    from notionwp.registry import build_config
    from test_gate_schema import DEFAULTS

    cfg, _ = build_config(DEFAULTS, registry_row(**{"유튜브 채널": "@CleartoneClinic"}))
    assert cfg.wordpress.youtube_channel == "@CleartoneClinic"

    blank, _ = build_config(DEFAULTS, registry_row())
    assert blank.wordpress.youtube_channel == ""


# ------------------------------------------------------------------ 목록 조회


class FakeSession:
    def __init__(self, payloads=None, text="", fail=False):
        self._payloads = list(payloads or [])
        self._text = text
        self._fail = fail
        self.urls: list[str] = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        if self._fail:
            raise requests.ConnectionError("끊김")
        return FakeResponse(self._payloads.pop(0) if self._payloads else {}, self._text)


class FakeResponse:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


CHANNELS = {"items": [{"id": "UC" + "x" * 22, "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}


def playlist(*titles, token=None):
    return {
        "items": [
            {"snippet": {"title": t, "resourceId": {"videoId": f"vid{i}"}, "publishedAt": "2026-08-01T00:00:00Z"}}
            for i, t in enumerate(titles)
        ],
        **({"nextPageToken": token} if token else {}),
    }


def test_api_path_returns_the_whole_channel():
    session = FakeSession([CHANNELS, playlist("기미 악화시키는 TOP5", "울쎄라VS써마지")])
    videos = list_videos("@CleartoneClinic", key="AIzaTEST", session=session)

    assert [v.title for v in videos] == ["기미 악화시키는 TOP5", "울쎄라VS써마지"]
    assert videos[0].url == "https://www.youtube.com/watch?v=vid0"
    assert videos[0].published == "2026-08-01"


def test_api_path_follows_pagination():
    session = FakeSession([CHANNELS, playlist("A", token="next"), playlist("B")])
    assert [v.title for v in list_videos("UC" + "x" * 22, key="k", session=session)] == ["A", "B"]


def test_unavailable_videos_are_dropped():
    session = FakeSession([CHANNELS, playlist("Private video", "실제 영상", "Deleted video")])
    assert [v.title for v in list_videos("UC" + "x" * 22, key="k", session=session)] == ["실제 영상"]


RSS = """<feed><entry><title>기미 치료 이후 더 진해지는 이유</title>
<yt:videoId>abc12345678</yt:videoId><published>2026-05-02T00:00:00+00:00</published></entry></feed>"""


def test_rss_fallback_when_there_is_no_key():
    session = FakeSession(text=RSS)
    videos = list_videos("UC" + "x" * 22, key="", session=session)

    assert [v.title for v in videos] == ["기미 치료 이후 더 진해지는 이유"]
    assert "feeds/videos.xml" in session.urls[0]


def test_api_failure_falls_back_to_rss():
    class FailThenRss(FakeSession):
        def get(self, url, params=None, timeout=None):
            self.urls.append(url)
            if "googleapis" in url:
                raise requests.ConnectionError("API 죽음")
            return FakeResponse({}, RSS)

    videos = list_videos("UC" + "x" * 22, key="k", session=FailThenRss())
    assert len(videos) == 1  # 키가 있어도 실패하면 RSS로 내려갑니다


def test_lookup_failure_is_not_fatal():
    assert list_videos("UC" + "x" * 22, key="k", session=FakeSession(fail=True)) == []


def test_no_channel_means_no_candidates():
    assert list_videos("", key="k") == []


# ------------------------------------------------------------------ 본문 삽입


def test_embed_block_is_a_real_gutenberg_embed():
    html = render([video_block(url="https://www.youtube.com/watch?v=abc", note="영상 설명")])

    assert "wp:embed" in html
    assert '"providerNameSlug":"youtube"' in html
    assert "wp-embed-aspect-16-9" in html
    assert "영상 설명" in html


def publish_with(plan_video: VideoChoice | None, tmp_path: Path):
    plan = PagePlan(
        page_id="e2868fa2-06ff-8387-a4ce-018c082c51d5",
        title="제목",
        slug="melasma-laser-sessions",
        images=[],
        thumbnail_alt="썸네일 설명",
    )
    if plan_video:
        plan.video = plan_video
    directory = tmp_path / plan.page_id.replace("-", "")
    plan.save(directory)

    wp = FakeWordPress()
    notion = FakeNotion([complete_page()], sample_page())
    Publisher(CONFIG, notion=notion, wp=wp, plan_root=tmp_path).run()
    return next(iter(wp.posts.values()))["content"]


def test_chosen_video_lands_in_the_body(tmp_path):
    # 실제 영상 ID 는 11자입니다. 짧은 가짜 ID 는 '없는 영상' 으로 보고 링크로 바뀝니다.
    content = publish_with(
        VideoChoice(url="https://www.youtube.com/watch?v=kN0iB58w_6I", anchor=2, note="직접 설명합니다"),
        tmp_path,
    )
    assert "wp:embed" in content
    assert "직접 설명합니다" in content


def test_no_choice_means_no_embed(tmp_path):
    assert "wp:embed" not in publish_with(VideoChoice(), tmp_path)


def test_plan_without_video_key_still_loads(tmp_path):
    # 예전 회차가 남긴 plan.json 에는 video 칸이 없습니다.
    assert "wp:embed" not in publish_with(None, tmp_path)


# ------------------------------------------------------------------ 정렬


def test_candidates_come_back_newest_first():
    """주제가 맞는 것 중 최신을 고르라고 하므로, 목록이 최신순이어야 쉽습니다."""
    session = FakeSession(
        [
            CHANNELS,
            {
                "items": [
                    {"snippet": {"title": "오래된 기미 영상", "resourceId": {"videoId": "old"},
                                 "publishedAt": "2024-01-02T00:00:00Z"}},
                    {"snippet": {"title": "최신 기미 영상", "resourceId": {"videoId": "new"},
                                 "publishedAt": "2026-08-05T00:00:00Z"}},
                    {"snippet": {"title": "중간 기미 영상", "resourceId": {"videoId": "mid"},
                                 "publishedAt": "2025-05-05T00:00:00Z"}},
                ]
            },
        ]
    )
    videos = list_videos("UC" + "x" * 22, key="k", session=session)

    assert [v.video_id for v in videos] == ["new", "mid", "old"]


def test_old_videos_are_kept_as_candidates():
    # 오래됐다는 이유로 후보에서 빼지 않습니다. 주제가 맞으면 그게 맞는 영상입니다.
    session = FakeSession(
        [
            CHANNELS,
            {"items": [{"snippet": {"title": "2년 전 기미 영상", "resourceId": {"videoId": "old"},
                                    "publishedAt": "2024-01-02T00:00:00Z"}}]},
        ]
    )
    assert [v.title for v in list_videos("UC" + "x" * 22, key="k", session=session)] == ["2년 전 기미 영상"]


# ------------------------------------------------- 퍼가기가 막힌 영상 (임베드 불가)

from notionwp.gutenberg import youtube_link  # noqa: E402
from notionwp.youtube import embeddable, video_id_of  # noqa: E402
import notionwp.publish as publish_mod  # noqa: E402


def status_payload(**flags):
    """videos.list(status) 응답. flags = {videoId: (embeddable, privacy)}"""
    return {"items": [{"id": vid, "status": {"embeddable": emb, "privacyStatus": priv}}
                      for vid, (emb, priv) in flags.items()]}


def test_videos_that_forbid_embedding_are_not_candidates():
    """지혜로운 필라테스 '클래식과 모던필라테스 3가지 차이점' — 공개지만 퍼가기가 꺼져 있었습니다.

    embed 블록으로 넣으면 빈 16:9 상자와 맨 URL 만 남습니다. 후보에서 뺍니다.
    """
    session = FakeSession([CHANNELS, playlist("임베드 되는 영상", "퍼가기 막힌 영상", "비공개로 바뀐 영상"),
                           status_payload(vid0=(True, "public"), vid1=(False, "public"), vid2=(True, "private"))])
    videos = list_videos("UC" + "x" * 22, key="k", session=session)
    assert [v.title for v in videos] == ["임베드 되는 영상"]
    assert any("googleapis.com/youtube/v3/videos" in u for u in session.urls)


def test_a_failed_status_check_keeps_the_list_instead_of_emptying_it():
    class StatusFails(FakeSession):
        def get(self, url, params=None, timeout=None):
            if url.endswith("/videos"):
                raise requests.ConnectionError("status 죽음")
            return super().get(url, params, timeout)

    session = StatusFails([CHANNELS, playlist("A", "B")])
    assert [v.title for v in list_videos("UC" + "x" * 22, key="k", session=session)] == ["A", "B"]


class OEmbedSession:
    def __init__(self, code):
        self.code = code

    def get(self, url, params=None, timeout=None):
        r = FakeResponse({})
        r.status_code = self.code
        return r


def test_oembed_tells_embeddable_from_forbidden():
    url = "https://www.youtube.com/watch?v=rEekgNZIwpw"
    assert embeddable(url, session=OEmbedSession(200)) is True
    assert embeddable(url, session=OEmbedSession(401)) is False   # 퍼가기 꺼짐
    assert embeddable(url, session=OEmbedSession(404)) is False   # 없는 영상(옮겨 적다 틀린 주소)
    assert embeddable(url, session=OEmbedSession(500)) is None    # 모르면 막지 않습니다
    assert embeddable("https://example.com/not-a-video") is False


def test_video_id_is_read_from_any_youtube_url_shape():
    assert video_id_of("https://www.youtube.com/watch?v=rEekgNZIwpw") == "rEekgNZIwpw"
    assert video_id_of("https://youtu.be/rEekgNZIwpw") == "rEekgNZIwpw"
    assert video_id_of("https://www.youtube.com/shorts/rEekgNZIwpw") == "rEekgNZIwpw"
    assert video_id_of("") == ""


def test_link_block_replaces_the_embed_when_embedding_is_forbidden():
    html = youtube_link("https://www.youtube.com/watch?v=abc", note="영상으로 정리했습니다")
    assert "wp:embed" not in html and "wp:paragraph" in html
    assert "영상으로 정리했습니다" in html and "유튜브에서 영상 보기" in html
    assert 'href="https://www.youtube.com/watch?v=abc"' in html


def test_publish_falls_back_to_a_link_and_warns_when_embedding_is_forbidden(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_mod, "embeddable", lambda url: False)
    plan = PagePlan(page_id="e2868fa2-06ff-8387-a4ce-018c082c51d5", title="제목", slug="melasma-laser-sessions",
                    images=[], thumbnail_alt="썸네일 설명")
    plan.video = VideoChoice(url="https://www.youtube.com/watch?v=rEekgNZIwpw", anchor=2, note="영상으로 정리했습니다")
    plan.save(tmp_path / plan.page_id.replace("-", ""))
    wp = FakeWordPress()
    outcomes = Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp, plan_root=tmp_path).run()
    content = next(iter(wp.posts.values()))["content"]

    assert "wp:embed" not in content
    assert "유튜브에서 영상 보기" in content and "영상으로 정리했습니다" in content
    assert any("임베드를 허용하지 않아" in w for o in outcomes for w in o.warnings)


def test_publish_embeds_normally_when_youtube_allows_it(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_mod, "embeddable", lambda url: True)
    plan = PagePlan(page_id="e2868fa2-06ff-8387-a4ce-018c082c51d5", title="제목", slug="melasma-laser-sessions",
                    images=[], thumbnail_alt="썸네일 설명")
    plan.video = VideoChoice(url="https://www.youtube.com/watch?v=kN0iB58w_6I", anchor=2, note="설명")
    plan.save(tmp_path / plan.page_id.replace("-", ""))
    wp = FakeWordPress()
    outcomes = Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp, plan_root=tmp_path).run()
    assert "wp:embed" in next(iter(wp.posts.values()))["content"]
    assert not any("임베드" in w for o in outcomes for w in o.warnings)


def test_a_chosen_url_outside_the_candidate_list_is_flagged_as_a_possible_typo(tmp_path, monkeypatch):
    """I 와 l 처럼 헷갈리는 글자를 옮겨 적다 틀리면 후보에 없는 주소가 됩니다."""
    from notionwp.plan import VideoCandidate
    monkeypatch.setattr(publish_mod, "embeddable", lambda url: None)
    plan = PagePlan(page_id="e2868fa2-06ff-8387-a4ce-018c082c51d5", title="제목", slug="melasma-laser-sessions",
                    images=[], thumbnail_alt="썸네일 설명")
    plan.video_candidates = [VideoCandidate(title="진짜", url="https://www.youtube.com/watch?v=rEekgNZIwpw")]
    plan.video = VideoChoice(url="https://www.youtube.com/watch?v=rEekgNZlwpw", anchor=2)  # l 로 잘못 적음
    plan.save(tmp_path / plan.page_id.replace("-", ""))
    wp = FakeWordPress()
    outcomes = Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp, plan_root=tmp_path).run()
    assert any("후보 목록에 없습니다" in w for o in outcomes for w in o.warnings)
