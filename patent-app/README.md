# 논문 → 특허 분석·작성기

연구 논문(PDF)을 올리면 다음을 자동으로 수행하는 로컬 웹앱입니다.

1. **특허 가능성 분석** — 신규성 / 진보성 / 산업상 이용가능성 관점 판정
2. **선행특허(중복) 검색** — KIPRIS Open API로 유사 등록·공개 특허 조회
3. **중복 회피·보완 가이드** — 겹치는 특허별 중복도와 청구항 보완 방향 제시
4. **특허 명세서 초안 생성** — 한국 특허 명세서 형식의 초안 작성 + **PDF 다운로드**

> ⚠️ 생성물은 AI 초안입니다. 실제 출원 전 반드시 변리사 검토를 받으세요.

## 설치

```bash
pip install -r requirements.txt
```

## 환경설정

`.env.example` 를 `.env` 로 복사한 뒤 키를 채웁니다.

| 변수 | 설명 | 없을 때 |
|------|------|---------|
| `ANTHROPIC_API_KEY` | Claude API 키 ([console.anthropic.com](https://console.anthropic.com)) | 분석·명세서가 규칙 기반 폴백으로 제한 동작 |
| `ANALYSIS_MODEL` | 사용할 모델 (기본 `claude-sonnet-4-6`, 품질 우선 시 `claude-opus-4-8`) | 기본값 사용 |
| `KIPRIS_API_KEY` | KIPRIS 서비스키 | 선행특허 검색만 비활성, 나머지는 정상 |

### KIPRIS 서비스키 발급 (무료)
1. [plus.kipris.or.kr](https://plus.kipris.or.kr) 회원가입
2. 마이페이지 → API 서비스 신청 → **특허·실용신안 정보검색** 활용신청
3. 발급된 인증키(서비스키)를 `.env` 의 `KIPRIS_API_KEY` 에 입력

## 실행

```bash
uvicorn app.web:app --reload
```

브라우저에서 http://127.0.0.1:8000 접속 → 논문 PDF 업로드 → 결과 확인 → PDF 다운로드.

## 구조

```
app/
  config.py          설정(.env 로딩)
  pdf_extract.py     논문 PDF → 텍스트 (pdfplumber)
  llm.py             Claude 호출 공통 유틸
  analyzer.py        특허 가능성 분석 + 검색 키워드 도출
  kipris.py          KIPRIS 선행특허 검색
  differentiation.py 중복 비교 + 회피·보완 가이드
  drafter.py         특허 명세서 초안 생성
  pdf_export.py      결과 → 한글 PDF (reportlab)
  pipeline.py        전체 파이프라인 오케스트레이션
  web.py             FastAPI 라우트
templates/           index.html, result.html
static/style.css
```

## 비고
- 한글 PDF는 Windows 기본 폰트(맑은 고딕 등)를 자동 사용합니다.
- 스캔 이미지 PDF는 텍스트 추출이 어려우니 텍스트 기반 PDF를 권장합니다.
- 범위 밖: 전자출원 자동 제출, 도면 자동 생성, 영문/PCT 명세서.
