"""논문 → 특허 분석 전체 파이프라인을 한 번에 실행한다."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict

from . import analyzer, differentiation, drafter, kipris, pdf_export
from .kipris import SearchResult
from .pdf_extract import extract_text


@dataclass
class PipelineResult:
    result_id: str
    paper_name: str
    analysis: Dict
    search: SearchResult
    diff: Dict
    spec: Dict
    pdf_path: str = ""
    warnings: list[str] = field(default_factory=list)


def run(pdf_bytes: bytes, paper_name: str) -> PipelineResult:
    """업로드된 논문 PDF 한 건에 대해 분석→검색→비교→작성→PDF 까지 수행."""
    result_id = uuid.uuid4().hex[:12]
    warnings: list[str] = []

    # 1) PDF → 텍스트
    paper_text = extract_text(pdf_bytes)

    # 2) 특허 가능성 분석 + 키워드 도출
    analysis = analyzer.analyze(paper_text)
    if analysis.get("_fallback"):
        warnings.append("ANTHROPIC_API_KEY 미설정: 특허 분석/명세서가 제한적으로 제공됩니다.")

    # 3) 선행특허 검색 (KIPRIS)
    search = kipris.search(analysis.get("search_keywords", []))
    if search.note:
        warnings.append(search.note)

    # 4) 중복 비교 + 회피/보완 가이드
    diff = differentiation.compare(analysis.get("core_features", []), search.patents)

    # 5) 명세서 초안 작성
    spec = drafter.draft(analysis, diff)

    # 6) PDF 생성
    pdf_path = pdf_export.build_pdf(
        paper_name=paper_name,
        analysis=analysis,
        search=search,
        diff=diff,
        spec=spec,
        out_id=result_id,
    )

    return PipelineResult(
        result_id=result_id,
        paper_name=paper_name,
        analysis=analysis,
        search=search,
        diff=diff,
        spec=spec,
        pdf_path=str(pdf_path),
        warnings=warnings,
    )
