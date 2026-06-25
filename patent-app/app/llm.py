"""Claude(Anthropic) 호출 공통 유틸.

여러 모듈(analyzer / differentiation / drafter)이 동일한 방식으로
Claude에게 'JSON 하나만' 또는 자유 텍스트를 받아내므로 공통화한다.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .config import settings


class LLMError(RuntimeError):
    """Claude 호출 또는 응답 파싱 실패."""


def call_claude(prompt: str, *, max_tokens: int = 2000, system: str | None = None) -> str:
    """Claude에 프롬프트를 보내고 텍스트 응답을 반환한다.

    ANTHROPIC_API_KEY 가 없으면 LLMError 를 던진다(호출 측에서 폴백 처리).
    """
    if not settings.anthropic_configured:
        raise LLMError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    kwargs: dict[str, Any] = {
        "model": settings.analysis_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    msg = client.messages.create(**kwargs)
    return "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    ).strip()


def parse_json(text: str) -> Any:
    """모델 응답에서 첫 번째 JSON 객체/배열을 추출해 파싱한다.

    코드펜스(```json ... ```)로 감싸여 있어도 동작한다.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    m = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
    if not m:
        raise LLMError("응답에서 JSON 을 찾지 못했습니다.")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:  # noqa: PERF203
        raise LLMError(f"JSON 파싱 실패: {e}") from e
