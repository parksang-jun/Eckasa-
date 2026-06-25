"""Instagram Graph API 릴스 게시 (Content Publishing).

3단계 플로우:
1) POST /{ig-user-id}/media  (media_type=REELS, video_url, caption)  -> creation_id(container)
2) GET  /{creation_id}?fields=status_code  를 폴링해 FINISHED 대기
3) POST /{ig-user-id}/media_publish (creation_id)                    -> 게시된 media id

요건:
- 인스타 '비즈니스' 계정 + 연결된 페이스북 페이지
- 앱에 instagram_business_content_publish 권한(App Review 승인)
- video_url 은 인스타 서버가 접근 가능한 '공개 URL'
- 24시간 100건 제한
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import settings
from . import db


class InstagramError(RuntimeError):
    pass


@dataclass
class PublishResult:
    media_id: str
    permalink: Optional[str]


def _base() -> str:
    return f"https://graph.facebook.com/{settings.ig_graph_version}"


def _check_configured() -> None:
    if not settings.instagram_configured:
        raise InstagramError(
            "인스타그램 설정이 비어 있습니다(.env 의 IG_USER_ID / IG_ACCESS_TOKEN)."
        )


def _guard_rate_limit() -> None:
    if db.count_posts_last_24h() >= 100:
        raise InstagramError("24시간 게시 한도(100건)에 도달했습니다.")


def create_container(client: httpx.Client, video_url: str, caption: str) -> str:
    url = f"{_base()}/{settings.ig_user_id}/media"
    resp = client.post(url, data={
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": settings.ig_access_token,
    })
    data = resp.json()
    if "id" not in data:
        raise InstagramError(f"컨테이너 생성 실패: {data}")
    return data["id"]


def wait_until_finished(client: httpx.Client, creation_id: str,
                        timeout: float = 300, interval: float = 5) -> None:
    url = f"{_base()}/{creation_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(url, params={
            "fields": "status_code,status",
            "access_token": settings.ig_access_token,
        })
        data = resp.json()
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise InstagramError(f"미디어 처리 실패: {data}")
        time.sleep(interval)
    raise InstagramError("미디어 처리 대기 시간 초과(영상 인코딩/다운로드 지연).")


def publish_container(client: httpx.Client, creation_id: str) -> str:
    url = f"{_base()}/{settings.ig_user_id}/media_publish"
    resp = client.post(url, data={
        "creation_id": creation_id,
        "access_token": settings.ig_access_token,
    })
    data = resp.json()
    if "id" not in data:
        raise InstagramError(f"게시 실패: {data}")
    return data["id"]


def fetch_permalink(client: httpx.Client, media_id: str) -> Optional[str]:
    try:
        resp = client.get(f"{_base()}/{media_id}", params={
            "fields": "permalink",
            "access_token": settings.ig_access_token,
        })
        return resp.json().get("permalink")
    except httpx.HTTPError:
        return None


def publish_reel(video_url: str, caption: str) -> PublishResult:
    """공개 video_url 을 릴스로 게시하고 결과를 반환한다."""
    _check_configured()
    _guard_rate_limit()

    with httpx.Client(timeout=60.0) as client:
        creation_id = create_container(client, video_url, caption)
        wait_until_finished(client, creation_id)
        media_id = publish_container(client, creation_id)
        permalink = fetch_permalink(client, media_id)
    return PublishResult(media_id=media_id, permalink=permalink)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python -m app.instagram <공개_video_url> [캡션]")
        raise SystemExit(1)
    cap = sys.argv[2] if len(sys.argv) > 2 else "ECKASA reel"
    res = publish_reel(sys.argv[1], cap)
    print("게시 완료:", res.media_id, res.permalink)
