"""Claude로 논문 핵심요소와 선행특허를 비교해 중복도/차별화·보완 가이드를 만든다.

산출물(dict):
{
  "overall": "전체 중복 위험 요약 2~4문장",
  "comparisons": [
    {
      "patent_title": "선행특허 명칭",
      "app_no": "출원번호",
      "overlap_level": "상|중|하",
      "overlapping_points": ["겹치는 구성/주장 1", ...],
      "differentiators": ["내 발명만의 차별점 1", ...],
      "amendment_advice": ["청구항 보완/한정 방향 1", ...]
    }, ...
  ],
  "strategy": ["전반적 회피·보완 전략 3~5개"]
}

선행특허가 없거나 AI 키가 없으면 안내성 폴백을 반환한다.
"""
from __future__ import annotations

import json
from typing import Dict, List

from .kipris import PriorPatent
from .llm import LLMError, call_claude, parse_json

_SYSTEM = (
    "당신은 대한민국 특허 청구항 작성과 선행기술 회피 전략에 정통한 변리사 보조 AI입니다. "
    "선행특허와 겹치는 부분을 정확히 짚고, 청구항을 어떻게 한정·보완하면 신규성/진보성을 "
    "확보할 수 있는지 실무적으로 조언합니다."
)


def _patents_block(patents: List[PriorPatent]) -> str:
    lines = []
    for i, p in enumerate(patents, 1):
        lines.append(
            f"[선행특허 {i}] 명칭: {p.title} / 출원번호: {p.app_no} / "
            f"출원인: {p.applicant} / 상태: {p.status}\n요약: {p.abstract or '(요약 없음)'}"
        )
    return "\n\n".join(lines)


def _build_prompt(core_features: List[str], patents: List[PriorPatent]) -> str:
    features = "\n".join(f"- {f}" for f in core_features) or "- (구성요소 미도출)"
    return f"""[내 발명의 핵심 구성요소]
{features}

[검색된 선행특허 목록]
{_patents_block(patents)}

각 선행특허에 대해 내 발명과의 중복도를 평가하고, 차별점과 청구항 보완 방향을 제시하세요.
다음 JSON 형식 '하나만' 출력하세요(설명/마크다운 금지):
{{
  "overall": "전체 중복 위험 요약 2~4문장",
  "comparisons": [
    {{
      "patent_title": "...",
      "app_no": "...",
      "overlap_level": "상|중|하",
      "overlapping_points": ["겹치는 부분 1~3개"],
      "differentiators": ["내 발명만의 차별점 1~3개"],
      "amendment_advice": ["청구항 한정/보완 방향 1~3개"]
    }}
  ],
  "strategy": ["전반적 회피·보완 전략 3~5개"]
}}"""


def _no_patents() -> Dict:
    return {
        "overall": "검색된 선행특허가 없어 직접적인 중복 비교를 수행하지 못했습니다. "
        "다만 검색 키워드가 제한적일 수 있으니, 더 넓은 키워드로 재검색을 권장합니다.",
        "comparisons": [],
        "strategy": [
            "발명의 명칭/키워드를 바꿔 KIPRIS·Google Patents 등에서 추가 검색",
            "핵심 구성요소를 독립항으로, 세부 한정사항을 종속항으로 구조화",
        ],
        "_fallback": True,
    }


def compare(core_features: List[str], patents: List[PriorPatent]) -> Dict:
    if not patents:
        return _no_patents()
    try:
        raw = call_claude(_build_prompt(core_features, patents), max_tokens=3000, system=_SYSTEM)
        data = parse_json(raw)
        data.setdefault("comparisons", [])
        data.setdefault("strategy", [])
        return data
    except LLMError as e:
        print(f"[warn] 차별화 분석 폴백 사용: {e}")
        # 키 없을 때: 검색된 특허 목록만 표 형태로 넘긴다.
        return {
            "overall": "AI 키 미설정으로 자동 비교를 건너뛰었습니다. "
            "아래 선행특허 목록을 직접 검토하세요.",
            "comparisons": [
                {
                    "patent_title": p.title,
                    "app_no": p.app_no,
                    "overlap_level": "확인필요",
                    "overlapping_points": [],
                    "differentiators": [],
                    "amendment_advice": [],
                }
                for p in patents
            ],
            "strategy": ["ANTHROPIC_API_KEY 를 설정하면 자동 중복 비교/보완 가이드가 제공됩니다."],
            "_fallback": True,
        }


if __name__ == "__main__":  # 간단 점검용
    print(json.dumps(_no_patents(), ensure_ascii=False, indent=2))
