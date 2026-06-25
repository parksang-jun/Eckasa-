"""논문 PDF에서 텍스트를 추출한다."""
from __future__ import annotations

import io
import re

from .config import settings


class PdfExtractError(RuntimeError):
    """PDF 텍스트 추출 실패."""


def extract_text(data: bytes) -> str:
    """PDF 바이트에서 본문 텍스트를 추출해 정리된 문자열로 반환한다."""
    import pdfplumber

    try:
        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
    except Exception as e:  # noqa: BLE001
        raise PdfExtractError(f"PDF 를 읽을 수 없습니다: {e}") from e

    text = "\n".join(pages)
    # 과도한 공백/개행 정리
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) < 100:
        raise PdfExtractError(
            "PDF에서 충분한 텍스트를 추출하지 못했습니다. "
            "스캔 이미지 PDF라면 텍스트 기반 PDF로 변환 후 다시 시도하세요."
        )

    # 모델 입력 보호: 너무 길면 앞부분 위주로 자른다.
    if len(text) > settings.max_paper_chars:
        text = text[: settings.max_paper_chars] + "\n\n…(이하 생략)"
    return text
