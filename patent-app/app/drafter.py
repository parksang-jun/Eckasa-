"""Claude로 한국 특허 명세서 초안을 생성한다.

산출물(dict): 한국 특허 명세서의 표준 섹션들.
{
  "invention_title": "발명의 명칭",
  "technical_field": "기술분야",
  "background_art": "배경기술",
  "problem": "발명이 해결하려는 과제",
  "solution": "과제의 해결 수단",
  "effects": "발명의 효과",
  "claims": ["[청구항 1] ...", "[청구항 2] ...", ...],
  "abstract": "요약서",
}

differentiation(선행특허 회피 전략) 결과를 반영해 차별화된 청구항을 작성한다.
AI 키가 없으면 골격만 채운 템플릿을 반환한다.
"""
from __future__ import annotations

import json
from typing import Dict, List

from .llm import LLMError, call_claude, parse_json

_SYSTEM = (
    "당신은 대한민국 특허 명세서를 작성하는 변리사 보조 AI입니다. "
    "특허법 시행규칙의 명세서 양식과 청구항 작성 원칙(독립항/종속항, 단일성, 명확성)을 "
    "준수하여 출원 가능한 수준의 초안을 작성합니다."
)


def _build_prompt(analysis: Dict, diff: Dict) -> str:
    features = "\n".join(f"- {f}" for f in analysis.get("core_features", []))
    strategy = "\n".join(f"- {s}" for s in diff.get("strategy", []))
    return f"""아래 정보를 바탕으로 대한민국 특허 명세서 초안을 작성하세요.

[발명의 명칭 후보]
{analysis.get('title_suggestion', '')}

[핵심 구성요소]
{features or '- (미도출)'}

[선행특허 회피·차별화 전략]
{strategy or '- (해당 없음)'}

요구사항:
- 청구항은 독립항 1개 + 종속항 3~6개로, 위 차별화 전략이 반영되도록 구체적으로 한정.
- 각 청구항은 "[청구항 N]" 으로 시작.
- 배경기술/과제/해결수단/효과는 명세서 어투(평서체)로 충실히 작성.

다음 JSON 형식 '하나만' 출력하세요(설명/마크다운 금지):
{{
  "invention_title": "...",
  "technical_field": "...",
  "background_art": "...",
  "problem": "...",
  "solution": "...",
  "effects": "...",
  "claims": ["[청구항 1] ...", "[청구항 2] ..."],
  "abstract": "..."
}}"""


def _template(analysis: Dict) -> Dict:
    title = analysis.get("title_suggestion", "발명")
    return {
        "invention_title": title,
        "technical_field": f"본 발명은 {title}에 관한 것이다. (AI 키 설정 시 자동 작성)",
        "background_art": "ANTHROPIC_API_KEY 를 설정하면 배경기술이 자동 작성됩니다.",
        "problem": "ANTHROPIC_API_KEY 를 설정하면 해결과제가 자동 작성됩니다.",
        "solution": "ANTHROPIC_API_KEY 를 설정하면 해결수단이 자동 작성됩니다.",
        "effects": "-",
        "claims": ["[청구항 1] (AI 키 설정 후 자동 생성)"],
        "abstract": "-",
        "_fallback": True,
    }


def draft(analysis: Dict, diff: Dict) -> Dict:
    try:
        raw = call_claude(_build_prompt(analysis, diff), max_tokens=4000, system=_SYSTEM)
        data = parse_json(raw)
        claims = data.get("claims", [])
        data["claims"] = [str(c).strip() for c in claims if str(c).strip()]
        if not data["claims"]:
            data["claims"] = ["[청구항 1] " + data.get("solution", title_or(analysis))]
        return data
    except LLMError as e:
        print(f"[warn] 명세서 폴백 사용: {e}")
        return _template(analysis)


def title_or(analysis: Dict) -> str:
    return analysis.get("title_suggestion", "발명")


if __name__ == "__main__":
    print(json.dumps(_template({"title_suggestion": "테스트 발명"}), ensure_ascii=False, indent=2))
