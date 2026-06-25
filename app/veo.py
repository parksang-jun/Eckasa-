"""Veo 3.1 (fal.ai) — 말하는 시네마틱 영상 생성.

가방+모델 장면 이미지를 시작 프레임으로, 모델이 한국어로 가방을 설명하며(립싱크)
영화 같은 카메라 모션과 사운드까지 한 번에 생성한다. (image-to-video + 오디오)

비용: Fast 변형 기준 초당 과금. 8초 1편에 대략 $1.5~3 수준(해상도/오디오에 따라).
FAL_KEY 필요.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import httpx

from .config import OUTPUT_DIR, settings


def _build_veo_prompt(scene_desc: str, dialogue: str) -> str:
    """Veo 용 프롬프트: 시네마틱 모션 + 한국어 대사(말하기) + 가방 유지."""
    return (
        f"Cinematic commercial video. {scene_desc} "
        f"The female model looks at the camera and speaks in Korean in a friendly, "
        f"cheerful voice, saying: \"{dialogue}\". Natural lip-sync, smooth cinematic "
        f"camera movement, film-like lighting, photorealistic. "
        f"The bag stays exactly identical to the one in the input image — same shape, "
        f"color, logo and design. Do not change the bag."
    )


def generate_talking_clip(image_path: str, scene_desc: str, dialogue: str,
                          out_name: str,
                          duration: Optional[str] = None,
                          resolution: Optional[str] = None) -> Optional[str]:
    """장면 이미지 → 말하는 시네마틱 영상(mp4) 경로. 실패 시 None."""
    if not settings.fal_key.strip():
        return None
    src = Path(image_path)
    if not src.exists():
        return None

    try:
        import fal_client

        os.environ.setdefault("FAL_KEY", settings.fal_key)
        image_url = fal_client.upload_file(str(src))
        prompt = _build_veo_prompt(scene_desc, dialogue)

        result = fal_client.subscribe(
            settings.veo_model,
            arguments={
                "prompt": prompt,
                "image_url": image_url,
                "duration": duration or settings.veo_duration,
                "resolution": resolution or settings.veo_resolution,
                "aspect_ratio": "9:16",
                "generate_audio": True,
            },
            with_logs=False,
        )

        video = result.get("video") if isinstance(result, dict) else None
        url = video.get("url") if isinstance(video, dict) else (
            video if isinstance(video, str) else None)
        if not url:
            print(f"[warn] Veo 응답에서 영상 URL 없음: {result}")
            return None

        out_path = OUTPUT_DIR / "talking" / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)
        return str(out_path)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Veo 영상 생성 실패: {e}")
        return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python -m app.veo <이미지> "<대사>"')
        raise SystemExit(1)
    p = generate_talking_clip(
        sys.argv[1], "The model presents the bag.", sys.argv[2],
        f"test_{int(time.time())}.mp4")
    print("생성됨:", p)
