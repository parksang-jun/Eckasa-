"""제품 1건 → 릴스 광고 제작 → (선택) 게시까지의 전체 파이프라인.

각 단계 진행상황을 jobs 테이블에 기록해 대시보드에서 추적할 수 있다.

run_job(product_id, publish=True) 가 핵심 진입점이며,
대시보드(버튼)와 스케줄러가 공통으로 호출한다.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Optional

from .config import OUTPUT_DIR, settings
from . import (ai_video, cancel, composer, copywriter, db, instagram, presets,
               scene, uploader, veo)


class JobCancelled(Exception):
    """사용자가 작업을 취소했을 때."""


def _ckpt(job_id: int) -> None:
    """취소 요청이 있으면 작업을 중단한다. 각 단계 시작 전에 호출."""
    if cancel.is_cancelled(job_id):
        cancel.clear(job_id)
        db.update_job(job_id, status="canceled", stage_msg="사용자가 취소함")
        raise JobCancelled()


def _full_caption(caption: str, hashtags: list[str]) -> str:
    tags = " ".join(hashtags) if hashtags else settings.default_hashtags
    return f"{caption}\n\n{tags}".strip()


def run_job(product_id: int, publish: bool = True,
            job_id: Optional[int] = None) -> dict:
    """제품 하나에 대해 카피→AI클립→합성→업로드→게시 를 수행한다."""
    product = db.get_product(product_id)
    if not product:
        raise ValueError(f"제품 {product_id} 를 찾을 수 없습니다.")
    if not product["images"]:
        raise ValueError(f"제품 {product_id} 에 이미지가 없습니다. 크롤링을 먼저 하세요.")

    job_id = job_id or db.create_job(product_id)

    try:
        # 1) 카피
        db.update_job(job_id, status="copy", stage_msg="광고 카피 생성 중")
        copy = copywriter.generate_copy(product["name"], product.get("price"))
        caption = _full_caption(copy["caption"], copy.get("hashtags", []))
        db.update_job(
            job_id,
            caption=caption,
            hashtags=" ".join(copy.get("hashtags", [])),
            subtitles_json=json.dumps(copy["subtitles"], ensure_ascii=False),
        )

        # 2) AI 클립 (가능할 때만; 안전모드면 인트로용 1개)
        ai_clip = None
        if settings.ai_video_enabled and product["images"]:
            db.update_job(job_id, status="clip", stage_msg="AI 영상 클립 생성 중")
            ai_clip = ai_video.generate_clip(
                product["images"][0], f"clip_{product_id}_{job_id}.mp4"
            )

        # 3) 합성
        db.update_job(job_id, status="compose", stage_msg="릴스 영상 합성 중")
        out_path = str(OUTPUT_DIR / f"reel_{product_id}_{job_id}.mp4")
        video_path = composer.compose_reel(
            images=product["images"],
            subtitles=copy["subtitles"],
            out_path=out_path,
            ai_clip=ai_clip,
            price=product.get("price"),
        )
        db.update_job(job_id, video_path=video_path)

        if not publish:
            db.update_job(job_id, status="done", stage_msg="영상 생성 완료(게시 안 함)")
            return {"job_id": job_id, "video_path": video_path, "published": False}

        # 4) 공개 업로드
        db.update_job(job_id, status="upload", stage_msg="공개 URL 업로드 중")
        public_url = uploader.upload_public(video_path, key=Path(video_path).name)
        db.update_job(job_id, public_url=public_url)

        # 5) 인스타 게시
        db.update_job(job_id, status="publish", stage_msg="인스타그램 게시 중")
        result = instagram.publish_reel(public_url, caption)
        db.create_post(job_id, product_id, result.media_id, result.permalink)
        db.update_job(job_id, status="done",
                      stage_msg=f"게시 완료: {result.permalink or result.media_id}")
        return {
            "job_id": job_id,
            "video_path": video_path,
            "published": True,
            "media_id": result.media_id,
            "permalink": result.permalink,
        }

    except Exception as e:  # noqa: BLE001
        db.update_job(job_id, status="error",
                      stage_msg="오류 발생", error=str(e))
        traceback.print_exc()
        raise


def run_prompt_job(product_id: int,
                   prompt: str,
                   publish: bool = False,
                   job_id: Optional[int] = None,
                   subtitles: Optional[list[str]] = None,
                   scene_count: Optional[int] = None) -> dict:
    """가방 이미지 + 프롬프트 1개 → 자동 릴스. (사용자가 가장 원하는 단순 UX)

    엔진: scene_image_provider(보통 fal nano-banana)로 가방 보존 장면 생성 →
    use_ai_video 면 Kling 모션, 아니면 ffmpeg 줌/패닝 → 자막·음악·실제 제품컷.

    subtitles  : 지정하면 자동 카피 대신 이 자막을 화면에 얹는다(장점 강조 등).
    scene_count: 지정하면 그만큼 장면 컷을 만든다(기본 settings.scene_count).
    """
    product = db.get_product(product_id)
    if not product:
        raise ValueError(f"제품 {product_id} 를 찾을 수 없습니다.")
    rep = _representative_image(product)
    if not rep:
        raise ValueError(f"제품 {product_id} 에 사용할 이미지가 없습니다.")
    prompt = (prompt or settings.default_scene_prompt).strip()
    count = scene_count or settings.scene_count

    job_id = job_id or db.create_job(product_id)
    try:
        if not settings.scene_image_enabled:
            raise RuntimeError(
                "장면 생성 키가 필요합니다. .env 의 FAL_KEY(유료, 가방 보존) 또는 "
                "GEMINI_API_KEY(결제 활성화 시)를 설정하세요."
            )

        _ckpt(job_id)
        db.update_job(job_id, status="copy", stage_msg="카피 생성 중")
        copy = copywriter.generate_copy(product["name"], product.get("price"))
        caption = _full_caption(copy["caption"], copy.get("hashtags", []))
        db.update_job(job_id, caption=caption,
                      hashtags=" ".join(copy.get("hashtags", [])),
                      subtitles_json=json.dumps(copy["subtitles"], ensure_ascii=False))

        _ckpt(job_id)
        db.update_job(job_id, status="clip", stage_msg="AI 장면 생성 중(가방 보존)")
        scene_images = scene.generate_from_prompt(
            rep, prompt, count=count, tag=f"p{product_id}_j{job_id}")
        if not scene_images:
            raise RuntimeError("장면 이미지 생성 실패(키/네트워크/모델 응답 확인).")

        _ckpt(job_id)
        scene_media = _animate_or_still(scene_images, product_id, job_id)

        _ckpt(job_id)
        db.update_job(job_id, status="compose", stage_msg="릴스 합성 중")
        out_path = str(OUTPUT_DIR / f"scene_{product_id}_{job_id}.mp4")
        closing = rep if settings.include_closing_shot else None
        subs = subtitles if subtitles else copy["subtitles"]
        video_path = composer.compose_scene_reel(
            scene_media=scene_media, subtitles=subs,
            out_path=out_path, closing_image=closing, price=product.get("price"))
        db.update_job(job_id, video_path=video_path)

        if not publish:
            db.update_job(job_id, status="done", stage_msg="릴스 생성 완료(게시 안 함)")
            return {"job_id": job_id, "video_path": video_path, "published": False}

        _ckpt(job_id)
        return _publish_video(job_id, product_id, video_path, caption)
    except JobCancelled:
        return {"job_id": job_id, "canceled": True}
    except Exception as e:  # noqa: BLE001
        db.update_job(job_id, status="error", stage_msg="오류 발생", error=str(e))
        traceback.print_exc()
        raise


def _animate_or_still(scene_images: list[str], product_id: int, job_id: int) -> list[str]:
    """use_ai_video 면 Kling 으로 영상화, 아니면 정지 장면(이후 Ken-Burns)."""
    if settings.ai_video_enabled and settings.use_ai_video:
        media: list[str] = []
        for i, img in enumerate(scene_images):
            clip = ai_video.generate_clip(img, f"scene_{product_id}_{job_id}_{i}.mp4")
            media.append(clip or img)
        return media
    return list(scene_images)


def _publish_video(job_id: int, product_id: int, video_path: str, caption: str) -> dict:
    db.update_job(job_id, status="upload", stage_msg="공개 URL 업로드 중")
    public_url = uploader.upload_public(video_path, key=Path(video_path).name)
    db.update_job(job_id, public_url=public_url)
    db.update_job(job_id, status="publish", stage_msg="인스타그램 게시 중")
    result = instagram.publish_reel(public_url, caption)
    db.create_post(job_id, product_id, result.media_id, result.permalink)
    db.update_job(job_id, status="done",
                  stage_msg=f"게시 완료: {result.permalink or result.media_id}")
    return {"job_id": job_id, "video_path": video_path, "published": True,
            "media_id": result.media_id, "permalink": result.permalink}


def _split_dialogue(text: str, n: int) -> list[str]:
    """대사를 문장 단위로 n개 구간으로 나눈다(클립별 대사). 부족하면 비워 둠."""
    import re as _re
    sentences = [s.strip() for s in _re.split(r"(?<=[.!?。!?\n])\s+", text) if s.strip()]
    if not sentences:
        return [text] + [""] * (n - 1)
    # n개 그룹으로 균등 분배
    groups: list[list[str]] = [[] for _ in range(n)]
    for i, s in enumerate(sentences):
        groups[min(i * n // len(sentences), n - 1)].append(s)
    out = [" ".join(g).strip() for g in groups]
    # 빈 구간은 마지막 비어있지 않은 대사를 이어가도록(말이 끊기지 않게) — 또는 침묵
    return out


def run_talking_job(product_id: int,
                    scene_desc: str,
                    dialogue: str,
                    publish: bool = False,
                    job_id: Optional[int] = None,
                    target_seconds: int = 8,
                    resolution: Optional[str] = None) -> dict:
    """말하는 시네마틱 영상 광고. (가방+모델 장면 → Veo 3.1 로 말+모션 영상)

    target_seconds: 최종 영상 길이(초). 8 초 초과 시 8 초 클립을 이어붙여 만든다(최대 30초).
    """
    product = db.get_product(product_id)
    if not product:
        raise ValueError(f"제품 {product_id} 를 찾을 수 없습니다.")
    rep = _representative_image(product)
    if not rep:
        raise ValueError(f"제품 {product_id} 에 사용할 이미지가 없습니다.")
    if not settings.fal_key.strip():
        raise RuntimeError("말하는 영상에는 fal.ai 가 필요합니다(.env 의 FAL_KEY).")

    scene_desc = (scene_desc or settings.default_scene_prompt).strip()
    dialogue = (dialogue or "이 가방 정말 예쁘죠? 방수도 완벽하고 데일리로 딱이에요!").strip()
    target_seconds = max(4, min(int(target_seconds), settings.max_video_seconds))
    clip_len = settings.veo_clip_seconds  # 8
    n_clips = max(1, -(-target_seconds // clip_len))  # ceil
    job_id = job_id or db.create_job(product_id)

    try:
        # 1) 가방 보존 장면 이미지 1장 (모델 + 배경 + 실제 가방)
        _ckpt(job_id)
        db.update_job(job_id, status="clip", stage_msg="AI 장면 이미지 생성 중(가방 보존)")
        scene_imgs = scene.generate_from_prompt(
            rep, scene_desc, count=1, tag=f"talk_p{product_id}_j{job_id}")
        if not scene_imgs:
            raise RuntimeError("장면 이미지 생성 실패(키/네트워크 확인).")

        # 2) Veo 클립 생성 — 8초 단위. 길면 앞 클립 마지막 프레임을 이어 연속성 유지.
        dur_str = f"{min(target_seconds, clip_len)}s" if n_clips == 1 else f"{clip_len}s"
        parts = _split_dialogue(dialogue, n_clips)
        clips: list[str] = []
        current_image = scene_imgs[0]
        for i in range(n_clips):
            _ckpt(job_id)
            db.update_job(job_id, status="compose",
                          stage_msg=f"말하는 영상 생성 중 {i+1}/{n_clips} (Veo, 클립당 1~3분)")
            clip = veo.generate_talking_clip(
                current_image, scene_desc, parts[i] or dialogue,
                out_name=f"talk_{product_id}_{job_id}_{i}.mp4",
                duration=dur_str, resolution=resolution)
            if not clip:
                if clips:  # 일부라도 만들어졌으면 그걸로 진행
                    break
                raise RuntimeError("Veo 영상 생성 실패(크레딧/파라미터/네트워크 확인).")
            clips.append(clip)
            if i < n_clips - 1:  # 다음 클립 시작 프레임 = 이번 클립 마지막 프레임
                nxt = str(OUTPUT_DIR / "talking" / f"talk_{product_id}_{job_id}_{i}_last.png")
                current_image = composer.extract_last_frame(clip, nxt) or scene_imgs[0]

        # 3) 클립 이어붙이기(+ 목표 길이로 트림)
        _ckpt(job_id)
        if len(clips) > 1:
            db.update_job(job_id, status="compose", stage_msg="클립 이어붙이는 중")
            final = str(OUTPUT_DIR / "talking" / f"talk_{product_id}_{job_id}.mp4")
            video_path = composer.concat_videos(clips, final, max_seconds=target_seconds)
        else:
            video_path = clips[0]

        # 캡션
        copy = copywriter.generate_copy(product["name"], product.get("price"))
        caption = _full_caption(copy["caption"], copy.get("hashtags", []))
        db.update_job(job_id, video_path=video_path, caption=caption,
                      hashtags=" ".join(copy.get("hashtags", [])))

        if not publish:
            db.update_job(job_id, status="done", stage_msg="말하는 영상 생성 완료(게시 안 함)")
            return {"job_id": job_id, "video_path": video_path, "published": False}

        _ckpt(job_id)
        return _publish_video(job_id, product_id, video_path, caption)
    except JobCancelled:
        return {"job_id": job_id, "canceled": True}
    except Exception as e:  # noqa: BLE001
        db.update_job(job_id, status="error", stage_msg="오류 발생", error=str(e))
        traceback.print_exc()
        raise


def run_manual_scene_job(product_id: int,
                         scene_images: list[str],
                         publish: bool = False,
                         job_id: Optional[int] = None) -> dict:
    """완전 무료 경로: 사용자가 (브라우저 AI Studio 등에서) 만든 장면 이미지를 올리면
    AI 호출 없이 줌/패닝 모션 + 자막 + 음악 + 실제 제품 컷으로 릴스를 합성한다."""
    product = db.get_product(product_id)
    if not product:
        raise ValueError(f"제품 {product_id} 를 찾을 수 없습니다.")
    imgs = [p for p in scene_images if p and Path(p).exists()]
    if not imgs:
        raise ValueError("업로드된 장면 이미지가 없습니다.")

    job_id = job_id or db.create_job(product_id)
    try:
        # 1) 카피 (무료: Anthropic 미설정 시 규칙 기반)
        db.update_job(job_id, status="copy", stage_msg="카피 생성 중")
        copy = copywriter.generate_copy(product["name"], product.get("price"))
        caption = _full_caption(copy["caption"], copy.get("hashtags", []))
        db.update_job(job_id, caption=caption,
                      hashtags=" ".join(copy.get("hashtags", [])),
                      subtitles_json=json.dumps(copy["subtitles"], ensure_ascii=False))

        # 2) 합성 (업로드 이미지 → Ken-Burns 모션, 마지막에 실제 제품 컷)
        db.update_job(job_id, status="compose", stage_msg="릴스 합성 중(무료)")
        rep = _representative_image(product)
        closing = rep if settings.include_closing_shot else None
        out_path = str(OUTPUT_DIR / f"scene_{product_id}_{job_id}.mp4")
        video_path = composer.compose_scene_reel(
            scene_media=imgs, subtitles=copy["subtitles"],
            out_path=out_path, closing_image=closing, price=product.get("price"),
        )
        db.update_job(job_id, video_path=video_path)

        if not publish:
            db.update_job(job_id, status="done", stage_msg="무료 장면 광고 생성 완료(게시 안 함)")
            return {"job_id": job_id, "video_path": video_path, "published": False}

        db.update_job(job_id, status="upload", stage_msg="공개 URL 업로드 중")
        public_url = uploader.upload_public(video_path, key=Path(video_path).name)
        db.update_job(job_id, public_url=public_url)
        db.update_job(job_id, status="publish", stage_msg="인스타그램 게시 중")
        result = instagram.publish_reel(public_url, caption)
        db.create_post(job_id, product_id, result.media_id, result.permalink)
        db.update_job(job_id, status="done",
                      stage_msg=f"게시 완료: {result.permalink or result.media_id}")
        return {"job_id": job_id, "video_path": video_path, "published": True,
                "media_id": result.media_id, "permalink": result.permalink}
    except JobCancelled:
        return {"job_id": job_id, "canceled": True}
    except Exception as e:  # noqa: BLE001
        db.update_job(job_id, status="error", stage_msg="오류 발생", error=str(e))
        traceback.print_exc()
        raise


def _representative_image(product: dict) -> Optional[str]:
    """광고 1개 = 가방 1개 원칙. 색상 변형이 섞이지 않도록 '대표 이미지 1장'만 고른다."""
    for im in product["images"]:
        if im and Path(im).exists():
            return im
    return None


def run_scene_job(product_id: int,
                  background_key: Optional[str] = None,
                  model_key: Optional[str] = None,
                  publish: bool = True,
                  job_id: Optional[int] = None) -> dict:
    """장면 광고: 가방 1개를 모델+이국적 배경과 합성해 릴스로 만들고 (선택) 게시한다."""
    product = db.get_product(product_id)
    if not product:
        raise ValueError(f"제품 {product_id} 를 찾을 수 없습니다.")
    rep = _representative_image(product)
    if not rep:
        raise ValueError(f"제품 {product_id} 에 사용할 이미지가 없습니다. 크롤링을 먼저 하세요.")

    background_key = background_key or settings.default_background
    model_key = model_key or settings.default_model
    job_id = job_id or db.create_job(product_id)

    bg_label = presets.get_background(background_key)["label"]
    md_label = presets.get_model(model_key)["label"]

    try:
        if not settings.scene_image_enabled:
            raise RuntimeError(
                "장면 광고에는 이미지 생성 키가 필요합니다. 무료: Google AI Studio 키를 "
                ".env 의 GEMINI_API_KEY 에 넣으세요(결제 불필요). 또는 유료 FAL_KEY."
            )

        # 1) 카피
        _ckpt(job_id)
        db.update_job(job_id, status="copy",
                      stage_msg=f"카피 생성 중 ({bg_label} · {md_label})")
        copy = copywriter.generate_copy(product["name"], product.get("price"))
        caption = _full_caption(copy["caption"], copy.get("hashtags", []))
        db.update_job(
            job_id, caption=caption,
            hashtags=" ".join(copy.get("hashtags", [])),
            subtitles_json=json.dumps(copy["subtitles"], ensure_ascii=False),
        )

        # 2) 장면 이미지 합성 (가방 유지 + 모델 + 배경)
        _ckpt(job_id)
        db.update_job(job_id, status="clip", stage_msg="AI 장면 이미지 생성 중")
        scene_images = scene.generate_scene_images(
            rep, background_key, model_key,
            count=settings.scene_count, tag=f"p{product_id}_j{job_id}",
        )
        if not scene_images:
            raise RuntimeError("장면 이미지 생성에 실패했습니다(모델 응답/네트워크 확인).")

        # 3) 모션: use_ai_video 면 Kling 영상화, 아니면 정지 장면→Ken-Burns
        db.update_job(job_id, status="clip", stage_msg="장면 모션 처리 중")
        scene_media = _animate_or_still(scene_images, product_id, job_id)

        # 4) 합성 (광고 1개 = 가방 1개)
        db.update_job(job_id, status="compose", stage_msg="릴스 합성 중")
        out_path = str(OUTPUT_DIR / f"scene_{product_id}_{job_id}.mp4")
        closing = rep if settings.include_closing_shot else None
        video_path = composer.compose_scene_reel(
            scene_media=scene_media,
            subtitles=copy["subtitles"],
            out_path=out_path,
            closing_image=closing,
            price=product.get("price"),
        )
        db.update_job(job_id, video_path=video_path)

        if not publish:
            db.update_job(job_id, status="done", stage_msg="장면 광고 생성 완료(게시 안 함)")
            return {"job_id": job_id, "video_path": video_path, "published": False}

        # 5) 공개 업로드 + 게시
        db.update_job(job_id, status="upload", stage_msg="공개 URL 업로드 중")
        public_url = uploader.upload_public(video_path, key=Path(video_path).name)
        db.update_job(job_id, public_url=public_url)

        db.update_job(job_id, status="publish", stage_msg="인스타그램 게시 중")
        result = instagram.publish_reel(public_url, caption)
        db.create_post(job_id, product_id, result.media_id, result.permalink)
        db.update_job(job_id, status="done",
                      stage_msg=f"게시 완료: {result.permalink or result.media_id}")
        return {"job_id": job_id, "video_path": video_path, "published": True,
                "media_id": result.media_id, "permalink": result.permalink}

    except JobCancelled:
        return {"job_id": job_id, "canceled": True}
    except Exception as e:  # noqa: BLE001
        db.update_job(job_id, status="error", stage_msg="오류 발생", error=str(e))
        traceback.print_exc()
        raise
