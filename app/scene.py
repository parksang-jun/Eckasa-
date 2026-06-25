"""장면 이미지 생성 (가방+모델+이국적 배경 합성).

제품 이미지 1장(가방) + 배경 프리셋 + 모델 프리셋 → 가방 형태를 '그대로 유지'한 채
모델이 그 가방을 들고 이국적 배경에 있는 합성 사진을 생성한다.

백엔드 2가지 (config.scene_image_provider 가 자동 선택):
- gemini : Google AI Studio(Gemini 2.5 Flash Image, 일명 nano-banana). 무료 키(결제X),
           하루 약 500장. → '무료 경로'. (gemini_api_key 필요)
- fal    : fal-ai/nano-banana/edit (유료, 이미지당 ≈$0.039). (fal_key 필요)

핵심 원칙:
- 광고 1개 = 가방 1개. 항상 '대표 이미지 1장'만 레퍼런스로 쓴다(색상 변형 섞지 않음).
- 프롬프트에 "가방의 형태/색/로고/디자인을 동일하게 유지" 지시를 강하게 넣어 왜곡을 막는다.

키가 하나도 없으면 [] 를 반환하고, 파이프라인이 안내 오류를 낸다.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional

import httpx

from .config import OUTPUT_DIR, settings
from . import presets

_KEEP_BAG = (
    "Keep the bag's exact shape, color, material, straps, logo and design completely "
    "unchanged and identical to the reference image. Do not redesign the bag. "
    "Photorealistic premium fashion advertisement, vertical 9:16 composition, high detail."
)


def _build_prompt(background_key: str, model_key: str, variation: str) -> str:
    bg = presets.get_background(background_key)["prompt"]
    model = presets.get_model(model_key)["prompt"]

    if model:  # 모델 포함
        return (
            f"Place this exact bag from the reference image into a brand-new photorealistic "
            f"scene. {model} is naturally carrying/holding this exact bag {bg}. "
            f"{variation}. {_KEEP_BAG}"
        )
    # 모델 없이 배경만
    return (
        f"Place this exact bag from the reference image as the hero product into a brand-new "
        f"photorealistic scene {bg}. {variation}. {_KEEP_BAG}"
    )


def _build_custom_prompt(user_prompt: str, variation: str) -> str:
    """사용자가 직접 쓴 프롬프트 + 가방 보존 지시 + 컷 변형."""
    return (
        f"Use the exact bag from the reference image. {user_prompt}. "
        f"{variation}. {_KEEP_BAG}"
    )


def generate_from_prompt(product_image: str, user_prompt: str,
                         count: Optional[int] = None,
                         tag: str = "scene") -> List[str]:
    """가방 이미지 + 사용자 프롬프트 1개 → 가방 보존 장면 이미지들(컷별 변형)."""
    provider = settings.scene_image_provider
    if provider == "none":
        return []
    src = Path(product_image)
    if not src.exists():
        return []
    count = count or settings.scene_count
    pool = presets.SCENE_VARIATIONS  # 컷 다양성(앵글/구도)
    prompts = [
        _build_custom_prompt(user_prompt, pool[i % len(pool)])
        for i in range(count)
    ]
    try:
        if provider == "gemini":
            return _generate_gemini(prompts, src, tag)
        return _generate_fal(prompts, src, tag)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 프롬프트 장면 생성 실패({provider}): {e}")
        return []


def scene_prompts(background_key: str, model_key: str,
                  count: Optional[int] = None) -> List[str]:
    """브라우저(무료 AI Studio)에 복붙해서 쓸 장면 프롬프트 목록(컷별)."""
    count = count or settings.scene_count
    return [
        _build_prompt(background_key, model_key, v)
        for v in _variations(model_key, count)
    ]


def _variations(model_key: str, count: int) -> List[str]:
    pool = (presets.SCENE_VARIATIONS_NO_MODEL
            if model_key == "no_model" else presets.SCENE_VARIATIONS)
    out = []
    for i in range(count):
        out.append(pool[i % len(pool)])
    return out


def _extract_image_urls(result: dict) -> List[str]:
    if not isinstance(result, dict):
        return []
    imgs = result.get("images")
    urls: List[str] = []
    if isinstance(imgs, list):
        for im in imgs:
            if isinstance(im, dict) and im.get("url"):
                urls.append(im["url"])
            elif isinstance(im, str):
                urls.append(im)
    if not urls and result.get("image"):
        img = result["image"]
        urls.append(img["url"] if isinstance(img, dict) else img)
    return urls


def _download(url: str, dest: Path) -> None:
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)


def _gemini_call_with_retry(client, model, contents, retries: int = 4):
    """429(분당 한도) 등에 대해 지수 백오프로 재시도한다."""
    delay = 8.0
    last_err = None
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = delay * (attempt + 1)
                print(f"[info] Gemini 분당 한도, {wait:.0f}s 대기 후 재시도...")
                time.sleep(wait)
                continue
            raise
    raise last_err


def _generate_gemini(prompts: List[str], src: Path, tag: str) -> List[str]:
    """Google Gemini로 장면 이미지를 생성한다(결제 활성화된 키 필요)."""
    from google import genai  # google-genai SDK
    from PIL import Image

    client = genai.Client(api_key=settings.gemini_api_key)
    ref_img = Image.open(src)

    out_paths: List[str] = []
    for i, prompt in enumerate(prompts):
        try:
            resp = _gemini_call_with_retry(
                client, settings.gemini_image_model, [prompt, ref_img])
            data = _extract_gemini_image(resp)
            if not data:
                print(f"[warn] Gemini 장면 {i}: 이미지 응답 없음")
                continue
            dest = OUTPUT_DIR / "scenes" / f"{tag}_{i}_{int(time.time())}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            out_paths.append(str(dest))
            time.sleep(2)  # 다음 컷 전 짧은 간격(분당 한도 완화)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Gemini 장면 {i} 실패: {e}")
    return out_paths


def _extract_gemini_image(resp) -> Optional[bytes]:
    try:
        for cand in resp.candidates:
            for part in cand.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    return inline.data
    except Exception:  # noqa: BLE001
        return None
    return None


def _generate_fal(prompts: List[str], src: Path, tag: str) -> List[str]:
    """fal.ai(유료 nano-banana)로 장면 이미지를 생성한다."""
    import fal_client

    os.environ.setdefault("FAL_KEY", settings.fal_key)
    ref_url = fal_client.upload_file(str(src))

    out_paths: List[str] = []
    for i, prompt in enumerate(prompts):
        try:
            result = fal_client.subscribe(
                settings.fal_image_model,
                arguments={
                    "prompt": prompt,
                    "image_urls": [ref_url],
                    "aspect_ratio": "9:16",
                    "num_images": 1,
                },
                with_logs=False,
            )
            urls = _extract_image_urls(result)
            if not urls:
                print(f"[warn] fal 장면 {i}: 이미지 URL 없음")
                continue
            dest = OUTPUT_DIR / "scenes" / f"{tag}_{i}_{int(time.time())}.png"
            _download(urls[0], dest)
            out_paths.append(str(dest))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] fal 장면 {i} 실패: {e}")
    return out_paths


def generate_scene_images(
    product_image: str,
    background_key: Optional[str] = None,
    model_key: Optional[str] = None,
    count: Optional[int] = None,
    tag: str = "scene",
) -> List[str]:
    """대표 제품 이미지 → 합성 장면 이미지 경로 목록. 실패/미설정 시 []."""
    provider = settings.scene_image_provider
    if provider == "none":
        return []
    src = Path(product_image)
    if not src.exists():
        return []

    background_key = background_key or settings.default_background
    model_key = model_key or settings.default_model
    count = count or settings.scene_count
    prompts = [
        _build_prompt(background_key, model_key, v)
        for v in _variations(model_key, count)
    ]

    try:
        if provider == "gemini":
            return _generate_gemini(prompts, src, tag)
        return _generate_fal(prompts, src, tag)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 장면 이미지 생성 실패({provider}): {e}")
        return []


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python -m app.scene <제품이미지경로> [background_key] [model_key]")
        raise SystemExit(1)
    bg = sys.argv[2] if len(sys.argv) > 2 else None
    md = sys.argv[3] if len(sys.argv) > 3 else None
    paths = generate_scene_images(sys.argv[1], bg, md)
    print("생성된 장면:", paths)
