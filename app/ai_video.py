"""fal.ai 이미지→영상 클립 생성.

- FAL_KEY 가 설정돼 있으면 제품 대표 이미지로 짧은 AI 클립(mp4)을 만든다.
- 미설정/실패 시 None 을 반환하고, composer 가 Ken-Burns(이미지 패닝)로 폴백한다.

안전모드(SAFE_MODE=true)에서는 가방 형태 왜곡을 줄이기 위해
"카메라가 천천히 움직이는" 정도의 미세한 모션 프롬프트만 사용한다.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import httpx

from .config import OUTPUT_DIR, settings

_SAFE_PROMPT = (
    "A premium product commercial shot of this bag. The bag stays exactly the same "
    "shape and design. Only a slow, subtle cinematic camera move and soft studio "
    "lighting. Clean background. No distortion, no morphing, photorealistic."
)
_DYNAMIC_PROMPT = (
    "A stylish, dynamic fashion commercial of this bag with elegant camera motion, "
    "soft light sparkle, premium look. Keep the bag's shape consistent. Photorealistic."
)


def _upload_image(client, image_path: Path) -> str:
    """로컬 이미지를 fal 에 업로드하고 접근 가능한 URL 을 받는다."""
    return client.upload_file(str(image_path))


def generate_clip(image_path: str, out_name: str) -> Optional[str]:
    """이미지 1장 → AI 영상 클립(mp4) 경로. 실패 시 None."""
    if not settings.ai_video_enabled:
        return None

    src = Path(image_path)
    if not src.exists():
        return None

    try:
        import fal_client

        # fal_client 는 환경변수 FAL_KEY 를 읽는다.
        import os
        os.environ.setdefault("FAL_KEY", settings.fal_key)

        image_url = fal_client.upload_file(str(src))
        prompt = _SAFE_PROMPT if settings.safe_mode else _DYNAMIC_PROMPT

        result = fal_client.subscribe(
            settings.fal_video_model,
            arguments={
                "image_url": image_url,
                "prompt": prompt,
                "duration": str(settings.ai_clip_seconds),
                "aspect_ratio": "9:16",
            },
            with_logs=False,
        )

        video_url = _extract_video_url(result)
        if not video_url:
            print("[warn] fal 응답에서 video url 을 찾지 못함")
            return None

        out_path = OUTPUT_DIR / "clips" / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _download(video_url, out_path)
        return str(out_path)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] AI 클립 생성 실패(폴백 사용): {e}")
        return None


def _extract_video_url(result: dict) -> Optional[str]:
    """모델마다 응답 구조가 조금씩 달라 방어적으로 탐색."""
    if not isinstance(result, dict):
        return None
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    if isinstance(video, str):
        return video
    videos = result.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, dict):
            return first.get("url")
        if isinstance(first, str):
            return first
    if result.get("url"):
        return result["url"]
    return None


def _download(url: str, dest: Path) -> None:
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python -m app.ai_video <이미지경로>")
        raise SystemExit(1)
    path = generate_clip(sys.argv[1], f"test_{int(time.time())}.mp4")
    print("생성됨:", path)
