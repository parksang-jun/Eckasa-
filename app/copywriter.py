"""Claude(Anthropic)로 릴스 광고 카피를 생성한다.

반환 구조(dict):
{
  "subtitles": ["짧은 자막1", "자막2", ...],   # 영상에 얹을 문구 (각 6~14자)
  "caption": "인스타 본문 캡션",
  "hashtags": ["#엑카사", "#가방", ...]
}

ANTHROPIC_API_KEY 가 없으면 규칙 기반 폴백 카피를 만든다.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List

from .config import settings

_TONE_GUIDE = {
    "emotional": "감성적이고 따뜻한, 라이프스타일을 떠올리게 하는 톤",
    "practical": "실용성과 기능(수납/보냉/내구성)을 강조하는 신뢰감 있는 톤",
    "trendy": "젊고 트렌디하며 짧고 임팩트 있는 SNS 광고 톤",
}


def _fallback(name: str, price: str | None) -> Dict:
    clean = re.sub(r"\[[^\]]*\]", "", name).strip() or name
    subs = [clean, "데일리로 딱", "지금 만나보세요"]
    if price:
        subs.insert(1, price)
    caption = (
        f"{settings.brand_name}의 '{clean}' 🛍️\n"
        f"감각적인 디자인과 실용성을 한 번에.\n"
        f"{'가격 ' + price if price else ''}\n프로필 링크에서 만나보세요!"
    ).strip()
    tags = [t for t in settings.default_hashtags.split() if t.startswith("#")]
    return {"subtitles": subs[:4], "caption": caption, "hashtags": tags}


def _build_prompt(name: str, price: str | None) -> str:
    tone = _TONE_GUIDE.get(settings.copy_tone, _TONE_GUIDE["trendy"])
    return f"""너는 패션 브랜드 '{settings.brand_name}'의 인스타그램 릴스 광고 카피라이터다.
아래 제품으로 세로형(9:16) 릴스 광고에 쓸 한국어 카피를 만들어라.

제품명: {name}
가격: {price or '미정'}
톤앤매너: {tone}

요구사항:
- subtitles: 영상 화면에 순서대로 띄울 짧은 자막 4개. 각 문구는 4~14자, 임팩트 있게.
- caption: 인스타 게시물 본문(2~4문장, 이모지 약간, 마지막에 행동유도 1문장).
- hashtags: 관련 해시태그 8~12개 (브랜드/카테고리/감성 키워드 혼합, 각 '#'로 시작).

반드시 아래 JSON 형식 '하나만' 출력하라(설명 금지):
{{"subtitles": ["...","...","...","..."], "caption": "...", "hashtags": ["#...","#..."]}}"""


def _parse_json(text: str) -> Dict:
    # 모델이 코드펜스로 감쌀 수 있으니 첫 번째 JSON 객체만 추출
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("JSON 파싱 실패")
    return json.loads(m.group(0))


def generate_copy(name: str, price: str | None = None) -> Dict:
    if not settings.anthropic_api_key.strip():
        return _fallback(name, price)

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.copy_model,
            max_tokens=800,
            messages=[{"role": "user", "content": _build_prompt(name, price)}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        data = _parse_json(text)

        subtitles: List[str] = [str(s).strip() for s in data.get("subtitles", []) if str(s).strip()]
        caption: str = str(data.get("caption", "")).strip()
        hashtags: List[str] = [
            ("#" + h.lstrip("#")) for h in data.get("hashtags", []) if str(h).strip()
        ]
        if not subtitles or not caption:
            return _fallback(name, price)
        return {"subtitles": subtitles[:5], "caption": caption, "hashtags": hashtags}
    except Exception as e:  # noqa: BLE001 - 어떤 오류든 폴백
        print(f"[warn] 카피 생성 실패, 폴백 사용: {e}")
        return _fallback(name, price)


if __name__ == "__main__":
    import sys

    n = sys.argv[1] if len(sys.argv) > 1 else "스퀘어 보냉백"
    print(json.dumps(generate_copy(n, "45,000원"), ensure_ascii=False, indent=2))
