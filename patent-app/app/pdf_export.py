"""분석 결과 + 명세서 초안을 한글 PDF로 생성한다 (reportlab)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from .config import OUTPUT_DIR
from .kipris import SearchResult

# --- 한글 폰트 등록 (윈도우 기본 폰트 후보를 순서대로 시도) ---
_FONT_NAME = "KFont"
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",      # 맑은 고딕
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\gulim.ttc",       # 굴림
    r"C:\Windows\Fonts\batang.ttc",      # 바탕
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # 리눅스 대비
]
_font_ready = False


def _ensure_font() -> str:
    """등록 가능한 한글 폰트를 찾아 등록하고 폰트명을 반환한다. 없으면 기본 폰트명."""
    global _font_ready
    if _font_ready:
        return _FONT_NAME
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, path))
                _font_ready = True
                return _FONT_NAME
            except Exception:  # noqa: BLE001 - 다음 후보 시도
                continue
    # 한글 폰트를 못 찾으면 내장 폰트(한글 깨짐 가능) 사용
    return "Helvetica"


def _styles(font: str):
    base = getSampleStyleSheet()
    styles = {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=font, fontSize=18,
                             leading=24, spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=font, fontSize=13,
                             leading=18, spaceBefore=10, spaceAfter=4, textColor="#1a3a6b"),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=font, fontSize=10.5,
                               leading=16, alignment=TA_LEFT, spaceAfter=4),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=font, fontSize=9,
                                leading=13, textColor="#555555"),
    }
    return styles


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_pdf(
    *,
    paper_name: str,
    analysis: Dict,
    search: SearchResult,
    diff: Dict,
    spec: Dict,
    out_id: str,
) -> Path:
    font = _ensure_font()
    s = _styles(font)
    out_path = OUTPUT_DIR / f"{out_id}.pdf"

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title="특허 분석 및 명세서 초안",
    )
    flow: List = []

    def P(text, style="body"):
        flow.append(Paragraph(_esc(text), s[style]))

    def bullets(items, style="body"):
        for it in items or []:
            flow.append(Paragraph("• " + _esc(it), s[style]))

    def rule():
        flow.append(Spacer(1, 4))
        flow.append(HRFlowable(width="100%", thickness=0.6, color="#cccccc"))
        flow.append(Spacer(1, 6))

    # 표지/요약
    P("특허 분석 및 명세서 초안", "h1")
    P(f"원문 논문: {paper_name}", "small")
    P("※ 본 문서는 AI가 생성한 초안이며, 실제 출원 전 변리사 검토가 필요합니다.", "small")
    rule()

    # 1. 특허 가능성 분석
    P("1. 특허 가능성 분석", "h2")
    P(f"종합 판정: {analysis.get('verdict', '-')}")
    P(f"제안 발명의 명칭: {analysis.get('title_suggestion', '-')}")
    P("핵심 구성요소", "small")
    bullets(analysis.get("core_features", []))
    P("신규성", "small"); P(analysis.get("novelty", "-"))
    P("진보성", "small"); P(analysis.get("inventive_step", "-"))
    P("산업상 이용가능성", "small"); P(analysis.get("industrial_applicability", "-"))
    P("판단 근거", "small"); bullets(analysis.get("reasons", []))
    rule()

    # 2. 선행특허 검색 결과
    P("2. 선행특허(중복) 검색 결과", "h2")
    P(f"검색 키워드: {', '.join(search.queried_keywords) or '-'}", "small")
    if search.note:
        P(search.note, "small")
    for i, p in enumerate(search.patents, 1):
        P(f"[{i}] {p.title}")
        P(f"출원번호 {p.app_no} · 출원인 {p.applicant} · 상태 {p.status} · 출원일 {p.app_date}", "small")
        if p.abstract:
            P(p.abstract, "small")
    rule()

    # 3. 중복 비교 및 보완 가이드
    P("3. 중복 비교 및 회피·보완 가이드", "h2")
    P(diff.get("overall", "-"))
    for c in diff.get("comparisons", []):
        P(f"· {c.get('patent_title', '')} (출원번호 {c.get('app_no', '')}) — 중복도: {c.get('overlap_level', '-')}")
        if c.get("overlapping_points"):
            P("겹치는 점", "small"); bullets(c["overlapping_points"], "small")
        if c.get("differentiators"):
            P("차별점", "small"); bullets(c["differentiators"], "small")
        if c.get("amendment_advice"):
            P("청구항 보완", "small"); bullets(c["amendment_advice"], "small")
    if diff.get("strategy"):
        P("종합 전략", "small"); bullets(diff["strategy"])
    rule()

    # 4. 특허 명세서 초안
    P("4. 특허 명세서 초안", "h2")
    P(f"【발명의 명칭】 {spec.get('invention_title', '-')}")
    P("【기술분야】", "small"); P(spec.get("technical_field", "-"))
    P("【배경기술】", "small"); P(spec.get("background_art", "-"))
    P("【발명이 해결하려는 과제】", "small"); P(spec.get("problem", "-"))
    P("【과제의 해결 수단】", "small"); P(spec.get("solution", "-"))
    P("【발명의 효과】", "small"); P(spec.get("effects", "-"))
    P("【청구범위】", "small"); bullets(spec.get("claims", []))
    P("【요약】", "small"); P(spec.get("abstract", "-"))

    doc.build(flow)
    return out_path
