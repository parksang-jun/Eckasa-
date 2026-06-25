"""KIPRIS(한국특허정보원) Open API로 선행특허를 검색한다.

특허·실용신안 검색 서비스(patUtiliModInfoSearchSevice)의 자유검색(getWordSearch)을
키워드별로 호출하고, 출원번호 기준으로 중복을 제거한 선행특허 목록을 반환한다.

KIPRIS_API_KEY 가 없으면 빈 목록과 안내 메시지를 반환한다(앱은 계속 동작).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import httpx
from lxml import etree

from .config import settings

# KIPRIS 응답 항목에서 읽을 후보 태그명(서비스/버전에 따라 표기가 다를 수 있어 여러 개 시도).
_FIELD_TAGS = {
    "title": ["inventionTitle", "InventionTitle", "title"],
    "applicant": ["applicantName", "ApplicantName", "applicant"],
    "app_no": ["applicationNumber", "ApplicationNumber", "applicationNo"],
    "app_date": ["applicationDate", "ApplicationDate", "appDate"],
    "status": ["registerStatus", "RegisterStatus", "registrationStatus"],
    "abstract": ["astrtCont", "abstractContent", "abstract"],
}


@dataclass
class PriorPatent:
    title: str = ""
    applicant: str = ""
    app_no: str = ""
    app_date: str = ""
    status: str = ""
    abstract: str = ""
    matched_keyword: str = ""


@dataclass
class SearchResult:
    patents: List[PriorPatent] = field(default_factory=list)
    note: str = ""  # 사용자에게 보여줄 안내(키 미설정/오류 등)
    queried_keywords: List[str] = field(default_factory=list)


def _first_text(item: etree._Element, tags: List[str]) -> str:
    for tag in tags:
        el = item.find(tag)
        if el is not None and el.text:
            return el.text.strip()
    return ""


def _parse_items(xml_bytes: bytes, keyword: str) -> List[PriorPatent]:
    root = etree.fromstring(xml_bytes)
    out: List[PriorPatent] = []
    # 어떤 래퍼 안에 있든 'item' 요소를 모두 수집.
    for item in root.iter("item"):
        p = PriorPatent(
            title=_first_text(item, _FIELD_TAGS["title"]),
            applicant=_first_text(item, _FIELD_TAGS["applicant"]),
            app_no=_first_text(item, _FIELD_TAGS["app_no"]),
            app_date=_first_text(item, _FIELD_TAGS["app_date"]),
            status=_first_text(item, _FIELD_TAGS["status"]),
            abstract=_first_text(item, _FIELD_TAGS["abstract"]),
            matched_keyword=keyword,
        )
        if p.title or p.app_no:
            out.append(p)
    return out


def search(keywords: List[str]) -> SearchResult:
    keywords = [k.strip() for k in keywords if k.strip()][:8]
    result = SearchResult(queried_keywords=keywords)

    if not settings.kipris_configured:
        result.note = (
            "KIPRIS_API_KEY 가 설정되지 않아 선행특허 검색을 건너뛰었습니다. "
            "plus.kipris.or.kr 에서 무료 서비스키를 발급받아 .env 에 입력하면 활성화됩니다."
        )
        return result
    if not keywords:
        result.note = "검색 키워드를 도출하지 못했습니다."
        return result

    seen: set[str] = set()
    errors = 0
    url = f"{settings.kipris_base_url}/getWordSearch"
    with httpx.Client(timeout=20.0) as client:
        for kw in keywords:
            params = {
                "word": kw,
                "numOfRows": settings.kipris_rows_per_keyword,
                "pageNo": 1,
                "accessKey": settings.kipris_api_key,
                "ServiceKey": settings.kipris_api_key,  # 구/신 표기 모두 대응
            }
            try:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                for p in _parse_items(resp.content, kw):
                    key = p.app_no or f"{p.title}|{p.applicant}"
                    if key in seen:
                        continue
                    seen.add(key)
                    result.patents.append(p)
            except Exception as e:  # noqa: BLE001 - 키워드 하나 실패해도 계속
                errors += 1
                print(f"[warn] KIPRIS 검색 실패(keyword={kw!r}): {e}")

    if not result.patents:
        if errors:
            result.note = (
                "KIPRIS 검색 중 오류가 발생했습니다. 서비스키(인증키)가 유효한지, "
                "해당 검색 서비스 사용 권한이 있는지 확인하세요."
            )
        else:
            result.note = "검색된 유사 선행특허가 없습니다(키워드 기준)."
    return result
