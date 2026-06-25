"""FastAPI 웹앱: 논문 PDF 업로드 → 특허 분석 → 결과/PDF 다운로드."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import pipeline
from .config import ROOT_DIR, settings
from .pdf_extract import PdfExtractError
from .pipeline import PipelineResult

app = FastAPI(title="논문→특허 분석·작성기")

TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 결과를 메모리에 보관 (단일 사용자/로컬 도구 가정).
_RESULTS: dict[str, PipelineResult] = {}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "anthropic_ok": settings.anthropic_configured,
            "kipris_ok": settings.kipris_configured,
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(request: Request, paper: UploadFile = File(...)):
    error = None
    if not paper.filename or not paper.filename.lower().endswith(".pdf"):
        error = "PDF 파일만 업로드할 수 있습니다."
    else:
        data = await paper.read()
        try:
            result = pipeline.run(data, paper.filename)
            _RESULTS[result.result_id] = result
            return templates.TemplateResponse(
                "result.html", {"request": request, "r": result}
            )
        except PdfExtractError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001
            error = f"처리 중 오류가 발생했습니다: {e}"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "error": error,
            "anthropic_ok": settings.anthropic_configured,
            "kipris_ok": settings.kipris_configured,
        },
        status_code=400,
    )


@app.get("/download/{result_id}")
def download(result_id: str):
    r = _RESULTS.get(result_id)
    if not r or not r.pdf_path or not Path(r.pdf_path).exists():
        return RedirectResponse("/", status_code=303)
    filename = f"특허분석_{Path(r.paper_name).stem}.pdf"
    return FileResponse(r.pdf_path, media_type="application/pdf", filename=filename)
