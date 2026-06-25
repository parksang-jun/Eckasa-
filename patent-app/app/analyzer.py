"""Claude로 논문을 분석한다.

산출물(dict):
{
  "title_suggestion": "발명의 명칭 후보",
  "core_features": ["핵심 발명 구성요소 1", ...],      # 청구항/검색의 기반
  "search_keywords": ["선행특허 검색용 키워드", ...],   # KIPRIS 검색에 사용
  "novelty": "신규성 관점 분석",
  "inventive_step": "진보성 관점 분석",
  "industrial_applicability": "산업상 이용가능성 분석",
  "verdict": "특허가능성 높음|보통|낮음",
  "reasons": ["판단 근거 1", ...]
}

ANTHROPIC_API_KEY 가 없으면 규칙 기반 폴백을 제공한다.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict

from .llm import LLMError, call_claude, parse_json

_SYSTEM = (
    "당신은 대한민국 특허 실무에 정통한 변리사 보조 AI입니다. "
    "신규성(제29조 제1항), 진보성(제29조 제2항), 산업상 이용가능성을 기준으로 "
    "논문의 특허 가능성을 냉정하고 구체적으로 평가합니다."
)


def _build_prompt(paper_text: str) -> str:
    return f"""아래는 연구 논문 전문(또는 일부)입니다. 이 논문 내용으로 특허 출원이 가능한지
분석하고, 선행특허 검색에 쓸 키워드와 핵심 발명 구성요소를 도출하세요.

[논문 내용 시작]
{paper_text}
[논문 내용 끝]

다음 JSON 형식 '하나만' 출력하세요(설명/마크다운 금지):
{{
  "title_suggestion": "이 발명에 적합한 '발명의 명칭' 한 줄",
  "core_features": ["특허 청구의 기반이 될 핵심 기술 구성요소를 5~8개, 각 한 문장"],
  "search_keywords": ["선행특허 검색용 핵심 기술 키워드 4~8개 (한국어, 명사 위주)"],
  "novelty": "신규성 관점에서 무엇이 새로운지/약한지 3~5문장",
  "inventive_step": "진보성(통상의 기술자가 쉽게 발명할 수 있는지) 관점 3~5문장",
  "industrial_applicability": "산업상 이용가능성 2~3문장",
  "verdict": "특허가능성 높음|보통|낮음 중 하나",
  "reasons": ["판단 근거 3~5개"]
}}"""


# --- 규칙 기반 폴백 -------------------------------------------------------

_STOPWORDS = {
    "그리고", "그러나", "또한", "이를", "통해", "위한", "대한", "있는", "있다", "한다",
    "이다", "에서", "으로", "하는", "되는", "결과", "연구", "본", "논문", "방법", "분석",
    "the", "and", "for", "with", "this", "that", "from", "are", "was", "were",
}


def _fallback(paper_text: str) -> Dict:
    # 한글 2글자 이상 + 영문 3글자 이상 토큰 빈도 상위를 키워드로.
    tokens = re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", paper_text)
    freq = Counter(t for t in tokens if t.lower() not in _STOPWORDS)
    keywords = [w for w, _ in freq.most_common(8)]
    return {
        "title_suggestion": (keywords[0] if keywords else "발명") + " 관련 장치 및 방법",
        "core_features": [
            "※ AI 키 미설정으로 자동 분석을 건너뛰었습니다. 논문 핵심 구성요소를 직접 정리하세요.",
        ],
        "search_keywords": keywords,
        "novelty": "ANTHROPIC_API_KEY 가 없어 AI 신규성 분석을 수행하지 못했습니다.",
        "inventive_step": "ANTHROPIC_API_KEY 를 설정하면 진보성 분석이 제공됩니다.",
        "industrial_applicability": "-",
        "verdict": "분석 불가(키 미설정)",
        "reasons": ["ANTHROPIC_API_KEY 를 .env 에 설정한 뒤 다시 시도하세요."],
        "_fallback": True,
    }


def analyze(paper_text: str) -> Dict:
    try:
        raw = call_claude(_build_prompt(paper_text), max_tokens=2500, system=_SYSTEM)
        data = parse_json(raw)
    except LLMError as e:
        print(f"[warn] 분석 폴백 사용: {e}")
        return _fallback(paper_text)

    # 최소 형식 보정
    data.setdefault("search_keywords", [])
    data.setdefault("core_features", [])
    data.setdefault("verdict", "보통")
    data["search_keywords"] = [str(k).strip() for k in data["search_keywords"] if str(k).strip()]
    if not data["search_keywords"]:
        data["search_keywords"] = _fallback(paper_text)["search_keywords"]
    return data
